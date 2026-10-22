import json
import datetime
import logging
from typing import Any, Dict, List, Set
from django.shortcuts import render, redirect
from django.views import View
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse

from .. import forms
from ..models import AddressRating, ScoutIntel
from ..scraper import scrape_sales, scrape_thrift_stores
from ..location_service import get_zip_from_coords, get_address_from_coords
from ..ai_service import AIService

logger = logging.getLogger(__name__)

class SaleDiscoveryView(LoginRequiredMixin, View):
    template_name: str = 'RouteFinderWeb/discover.html'
    
    def get(self, request: HttpRequest) -> HttpResponse:
        zip_code = request.GET.get('zip_code')
        radius = request.GET.get('radius', '15')
        mode = request.GET.get('mode', 'garage')
        sort_mode = request.GET.get('sort', 'time')
        refresh = request.GET.get('refresh') == 'true'
        
        # If no zip code provided in URL, try to use user's home zip
        if not zip_code and request.user.is_authenticated:
            zip_code = getattr(request.user.userprofile, 'home_zip', '')

        form = forms.SearchForm(initial={'zip_code': zip_code, 'radius': radius})
            
        # Check if saved intel exists for this user
        saved_intel_exists = ScoutIntel.objects.filter(user=request.user).exists()
        
        context = {
            'form': form,
            'mode': mode,
            'zip_code': zip_code,
            'radius': radius,
            'sort': sort_mode,
            'perform_search': bool(zip_code and refresh),
            'saved_intel_exists': saved_intel_exists,
            'is_authenticated': request.user.is_authenticated,
            'GOOGLE_MAPS_API_KEY': getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
        }
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest) -> HttpResponse:
        selected_addresses = [addr.strip() for addr in request.POST.getlist('selected_sales') if addr.strip()]
        mode = request.POST.get('mode', 'garage')
        
        # Get the cached discovery results to pull metadata from
        cached_results = request.session.get('discovery_results', [])
        cached_map = {s['address']: s for s in cached_results if isinstance(s, dict) and 'address' in s}
        
        if selected_addresses:
            other_addresses = request.session.get('other_addresses', [])
            
            # Extract plain string addresses for duplicate checking
            addr_list: List[str] = []
            for item in other_addresses:
                if isinstance(item, dict):
                    addr_list.append(item.get('address', ''))
                else:
                    addr_list.append(str(item))
                    
            # Ensure other_addresses is a structured list
            structured_addresses: List[Dict[str, Any]] = []
            for item in other_addresses:
                if isinstance(item, dict):
                    structured_addresses.append(item)
                else:
                    structured_addresses.append({'address': item, 'priority': 0, 'type': 'garage'})
                    
            for new_addr in selected_addresses:
                if new_addr not in addr_list:
                    # Enrich with metadata if available in cache
                    metadata = cached_map.get(new_addr, {})
                    entry = {
                        'address': new_addr, 
                        'priority': 0, 
                        'type': mode,
                        'title': metadata.get('title', ''),
                        'desc': metadata.get('desc', ''),
                        'tags': metadata.get('tags', []),
                        'is_treasure': metadata.get('is_treasure', False),
                        'treasure_reason': metadata.get('treasure_reason', ''),
                        'is_wishlist_match': metadata.get('is_wishlist_match', False),
                        'match_reason': metadata.get('match_reason', ''),
                        'is_community_event': metadata.get('is_community_event', False)
                    }
                    structured_addresses.append(entry)
                    
            request.session['other_addresses'] = structured_addresses
            # Dump to JSON string so JS can parse it in the template gracefully
            request.session['other_addresses_raw'] = json.dumps(structured_addresses)
            messages.success(request, f"Imported {len(selected_addresses)} sales into the route planner!")
            
        return redirect('main')


class DiscoveryDataView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> JsonResponse:
        zip_code = request.GET.get('zip_code')
        radius_str = request.GET.get('radius', '15')
        try:
            radius = int(radius_str)
        except ValueError:
            radius = 15
            
        mode = request.GET.get('mode', 'garage')
        sort_mode = request.GET.get('sort', 'time')
        force_refresh = request.GET.get('refresh') == 'true'
        
        if not zip_code:
            return JsonResponse({'success': False, 'error': 'Zip code required'})

        # Create a unique fingerprint for this search
        search_fingerprint = f"{zip_code}_{radius}_{mode}_{sort_mode}"
        
        # Check if we have this exact search cached in the session
        cached_fingerprint = request.session.get('discovery_cache_key')
        cached_results = request.session.get('discovery_results')
        
        # Fetch Route Planner addresses for "Already Imported" check
        planner_addresses: Set[str] = set()
        for item in request.session.get('other_addresses', []):
            if isinstance(item, dict):
                planner_addresses.add(item.get('address', ''))
            else:
                planner_addresses.add(str(item))

        cached_timestamp = request.session.get('discovery_timestamp')
        
        # Cache Expiry Hardening (2 hours)
        is_cache_stale = False
        if cached_timestamp:
            try:
                cached_dt = datetime.datetime.fromisoformat(cached_timestamp)
                if (datetime.datetime.now() - cached_dt).total_seconds() > 7200: # 2 hours
                    is_cache_stale = True
                    logger.info(f"Cache expired for {search_fingerprint}. Forcing fresh scout.")
            except Exception:
                is_cache_stale = True

        # Check if we should load from 'The Vault' (Saved Intel)
        if request.GET.get('mode') == 'saved':
            intel = ScoutIntel.objects.filter(user=request.user).first()
            if intel:
                logger.info(f"Loading 'The Vault' intel for {request.user.username}")
                return JsonResponse({'success': True, 'sales': intel.data, 'cached': True, 'timestamp': intel.updated_at.isoformat()})
            return JsonResponse({'success': False, 'error': 'No saved intel found'})

        if not force_refresh and not is_cache_stale and cached_fingerprint == search_fingerprint and cached_results:
            logger.info(f"Serving discovery results from cache for {search_fingerprint}")
            
            # Re-check import status even for cached results
            if isinstance(cached_results, list):
                for s in cached_results:
                    if isinstance(s, dict):
                        s['is_in_planner'] = s.get('address') in planner_addresses
                
            return JsonResponse({'success': True, 'sales': cached_results, 'cached': True})

        # If no cache or force refresh, perform the full scouting operation
        try:
            if mode == 'thrift':
                api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
                sales = scrape_thrift_stores(zip_code, api_key)
                
                # --- DONATION SURGE ENGINE ---
                try:
                    moving_sales_count = 0
                    local_garage_sales = scrape_sales(zip_code, radius=5)
                    if local_garage_sales:
                        ai = AIService(user=request.user)
                        garage_analysis = ai.analyze_listings_batch([s.get('desc', '') for s in local_garage_sales[:10]])
                        moving_sales_count = sum(1 for a in garage_analysis if a.get('is_moving_sale'))
                except Exception as se:
                    logger.error(f"Surge Engine Error: {se}")
                    moving_sales_count = 0

                if sales:
                    ai = AIService(user=request.user)
                    try:
                        thrift_analysis = ai.analyze_thrift_batch(sales)
                    except Exception as ai_err:
                        logger.error(f"AI Thrift Batch Analysis failed: {ai_err}")
                        thrift_analysis = []
                        
                    for i, s in enumerate(sales):
                        analysis = thrift_analysis[i] if (i < len(thrift_analysis) and thrift_analysis[i]) else {}
                        s['tags'] = analysis.get('tags', [])
                        s['is_potential_goldmine'] = analysis.get('is_potential_goldmine', False)
                        s['profit_rating'] = analysis.get('profit_rating', 'None')
                        s['profit_reason'] = analysis.get('profit_reason', '')
                        s['surge_count'] = moving_sales_count
                        s['is_surge_potential'] = moving_sales_count >= 2
                        s['is_treasure'] = False
                        s['is_bust_candidate'] = False
                        s['is_wishlist_match'] = False
            else:
                sales = scrape_sales(zip_code, radius)

            if not isinstance(sales, list):
                sales = []
                
            # Apply sorting logic
            if sort_mode == 'time':
                sales.sort(key=lambda x: x.get('start_time_sort', '9999-12-31 23:59') if isinstance(x, dict) else '')
            elif sort_mode == 'time_desc':
                sales.sort(key=lambda x: x.get('start_time_sort', '0000-01-01 00:00') if isinstance(x, dict) else '', reverse=True)
            elif sort_mode == 'title':
                sales.sort(key=lambda x: x.get('title', '').lower() if isinstance(x, dict) else '')
            
            if request.user.is_authenticated and sales:
                sale_addrs = [s.get('address') for s in sales if isinstance(s, dict)]
                ratings_qs = AddressRating.objects.filter(user=request.user, address__in=sale_addrs)
                historic_ratings = {rq.address: rq.rating for rq in ratings_qs}
                hidden_addrs = {rq.address for rq in ratings_qs if rq.is_hidden}
                
                # Filter out hidden sales
                sales = [s for s in sales if isinstance(s, dict) and s.get('address') not in hidden_addrs]
                
                if mode != 'thrift':
                    ai = AIService(user=request.user)
                    bust_history = list(AddressRating.objects.filter(user=request.user, rating='bust').exclude(notes='').values_list('notes', flat=True)[:10])
                    wishlist = getattr(request.user.userprofile, 'looking_for', '')
                    
                    # Batch analyze garage sales
                    descriptions = [s.get('desc', '') for s in sales if isinstance(s, dict)]
                    try:
                        ai_analysis = ai.analyze_listings_batch(descriptions, bust_history=bust_history, wishlist=wishlist)
                    except Exception as ai_err:
                        logger.error(f"AI Garage Batch Analysis failed: {ai_err}")
                        ai_analysis = []
                    
                    for i, s in enumerate(sales):
                        analysis = ai_analysis[i] if (i < len(ai_analysis) and ai_analysis[i]) else {}
                        s['tags'] = analysis.get('tags', [])
                        s['is_treasure'] = analysis.get('is_treasure', False)
                        s['treasure_reason'] = analysis.get('treasure_reason', "")
                        s['is_bust_candidate'] = analysis.get('is_bust_candidate', False)
                        s['bust_reason'] = analysis.get('bust_reason', "")
                        s['is_wishlist_match'] = analysis.get('is_wishlist_match', False)
                        s['match_reason'] = analysis.get('match_reason', "")
                        s['is_potential_goldmine'] = analysis.get('is_potential_goldmine', False)
                        s['profit_rating'] = analysis.get('profit_rating', 'None')
                        s['is_moving_sale'] = analysis.get('is_moving_sale', False)
                        title_lower = s.get('title', '').lower()
                        if any(word in title_lower for word in ['community', 'subdivision', 'sub-division', 'neighborhood']):
                            s['is_bust_candidate'] = False
                            s['is_community_event'] = True
                        else:
                            s['is_community_event'] = False

                    # AI Clustering
                    ai_clusters = ai.cluster_neighborhoods([s.get('title', '') for s in sales])
                    active_neighborhoods: Set[str] = set()
                    for cluster in ai_clusters:
                        indices = cluster.get('indices', [])
                        if any(sales[idx]['address'] in planner_addresses for idx in indices if idx < len(sales)):
                            active_neighborhoods.add(cluster.get('name', ''))

                    for cluster in ai_clusters:
                        c_name = cluster.get('name', 'Community Event')
                        indices = cluster.get('indices', [])
                        if len(indices) >= 2:
                            for idx in indices:
                                if idx < len(sales):
                                    sales[idx]['is_potential_duplicate'] = True
                                    sales[idx]['duplicate_count'] = len(indices)
                                    sales[idx]['neighborhood_name'] = c_name
                                    sales[idx]['community_is_active'] = c_name in active_neighborhoods

                # Final metadata loop
                for s in sales:
                    if isinstance(s, dict):
                        s['rating'] = historic_ratings.get(s.get('address', ''), 'neutral')
                        s['is_in_planner'] = s.get('address') in planner_addresses

                # Persist to 'The Vault' (DB) and Session Cache
                ScoutIntel.objects.update_or_create(
                    user=request.user,
                    defaults={'data': sales, 'metadata': {'zip_code': zip_code, 'radius': radius}}
                )
                request.session['discovery_cache_key'] = search_fingerprint
                request.session['discovery_results'] = sales
                request.session['discovery_timestamp'] = datetime.datetime.now().isoformat()
            
            return JsonResponse({'success': True, 'sales': sales, 'cached': False})
            
        except Exception as e:
            logger.exception("Discovery engine failed")
            return JsonResponse({'success': False, 'error': str(e)})


class ToggleRatingView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            data = json.loads(request.body)
            address = data.get('address')
            rating = data.get('rating')
            
            if not address or rating not in ['bust', 'great', 'neutral']:
                return JsonResponse({'error': 'Invalid data'}, status=400)
                
            obj, created = AddressRating.objects.get_or_create(user=request.user, address=address)
            if rating == 'neutral' and not obj.notes:
                obj.delete()
                logger.info(f"User {request.user.username} reset rating for '{address}'", extra={"action": "rating.toggle"})
            else:
                obj.rating = rating
                obj.save()
                logger.info(f"User {request.user.username} set rating '{rating}' for '{address}'", extra={"action": "rating.toggle"})
                
            return JsonResponse({'success': True, 'rating': rating})
        except Exception as e:
            logger.error(f"ToggleRatingView failed for user {request.user.username}: {e}", exc_info=True, extra={"action": "rating.toggle"})
            return JsonResponse({'error': str(e)}, status=500)


class GetZipCodeView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            data = json.loads(request.body)
            lat = data.get('lat')
            lon = data.get('lon')
            
            if lat is None or lon is None:
                return JsonResponse({'error': 'Missing coordinates'}, status=400)
                
            zip_code = get_zip_from_coords(lat, lon)
            
            if zip_code:
                logger.debug(f"Resolved zip code {zip_code} from coords ({lat}, {lon})", extra={"action": "location.get_zip"})
                return JsonResponse({'success': True, 'zip_code': zip_code})
            else:
                logger.warn(f"Could not determine zip code for coords ({lat}, {lon})", extra={"action": "location.get_zip"})
                return JsonResponse({'error': 'Could not determine zip code'}, status=404)
                
        except Exception as e:
            logger.error(f"GetZipCodeView failed: {e}", exc_info=True, extra={"action": "location.get_zip"})
            return JsonResponse({'error': str(e)}, status=500)


class HideSaleView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            data = json.loads(request.body)
            address = data.get('address')
            
            if not address:
                return JsonResponse({'error': 'Missing address'}, status=400)
                
            obj, created = AddressRating.objects.get_or_create(
                user=request.user, 
                address=address
            )
            obj.is_hidden = True
            obj.save()
            logger.info(f"User {request.user.username} hid sale at '{address}'", extra={"action": "sale.hide"})
            
            return JsonResponse({'success': True})
        except Exception as e:
            logger.error(f"HideSaleView failed for user {request.user.username}: {e}", exc_info=True, extra={"action": "sale.hide"})
            return JsonResponse({'error': str(e)}, status=500)


class GetAddressView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            data = json.loads(request.body)
            lat = data.get('lat')
            lon = data.get('lon')
            
            if lat is None or lon is None:
                return JsonResponse({'error': 'Missing coordinates'}, status=400)
                
            address = get_address_from_coords(lat, lon)
            
            if address:
                logger.debug(f"Resolved address '{address}' from coords ({lat}, {lon})", extra={"action": "location.get_address"})
                return JsonResponse({'success': True, 'address': address})
            else:
                logger.warn(f"Could not determine address for coords ({lat}, {lon})", extra={"action": "location.get_address"})
                return JsonResponse({'error': 'Could not determine address'}, status=404)
                
        except Exception as e:
            logger.error(f"GetAddressView failed: {e}", exc_info=True, extra={"action": "location.get_address"})
            return JsonResponse({'error': str(e)}, status=500)
