import json
import datetime
import urllib.parse
import logging
from typing import Any, Dict, List
from django.shortcuts import render, reverse
from django.views import View
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse, HttpResponseRedirect

from .. import forms
from ..models import AddressRating, ScoutIntel
from ..route_solver import RouteSolver

logger = logging.getLogger(__name__)

def generate_google_maps_urls(optimized_route: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    urls: List[Dict[str, str]] = []
    if not optimized_route or len(optimized_route) < 2:
        return urls
        
    chunk_size = 8  # max intermediate waypoints (1 origin + 1 dest + 8 wps = 10 stops)
    i = 0
    part = 1
    
    while i < len(optimized_route) - 1:
        origin = optimized_route[i]['address']
        waypoints = optimized_route[i+1 : i+1+chunk_size]
        dest_index = i + 1 + len(waypoints)
        
        if dest_index >= len(optimized_route):
            destination = waypoints.pop()['address']
            dest_index = len(optimized_route) - 1
        else:
            destination = optimized_route[dest_index]['address']
            
        base_url = "https://www.google.com/maps/dir/?api=1"
        origin_enc = urllib.parse.quote(origin)
        dest_enc = urllib.parse.quote(destination)
        url = f"{base_url}&origin={origin_enc}&destination={dest_enc}"
        
        if waypoints:
            wp_enc = "|".join(urllib.parse.quote(wp['address']) for wp in waypoints)
            url += f"&waypoints={wp_enc}"
            
        label = f"Open Route in Google Maps (Part {part})" if len(optimized_route) > 10 else "Open Route in Google Maps"
        
        urls.append({
            'label': label,
            'url': url
        })
        
        i = dest_index
        part += 1
        
    return urls

class MainView(LoginRequiredMixin, View):
    template_name: str = 'RouteFinderWeb/index_form.html'

    def get(self, request: HttpRequest) -> HttpResponse:
        initial_data: Dict[str, Any] = {}
        start_address = ""
        if request.user.is_authenticated and hasattr(request.user, 'userprofile'):
            profile = request.user.userprofile
            if profile.home_street:
                parts = [profile.home_street]
                if getattr(profile, 'home_city', ''): parts.append(profile.home_city)
                if profile.home_state: parts.append(profile.home_state)
                if profile.home_zip: parts.append(profile.home_zip)
                start_address = ", ".join(parts)
                initial_data['start'] = start_address
            initial_data['stop_mins'] = profile.default_stop_mins
            
        if 'other_addresses' in request.session:
            initial_data['addresses'] = request.session['other_addresses']
            
        form = forms.AddressForm(initial=initial_data)
        
        context = {
            'form': form,
            'start_address': start_address,
            'stop_mins': initial_data.get('stop_mins', 15),
            'other_addresses_json': json.dumps(request.session.get('other_addresses', []))
        }
        return render(request, self.template_name, context=context)

    def post(self, request: HttpRequest) -> HttpResponse:
        start_address = request.POST.get('start_address', '')
        start_time = request.POST.get('start_time', '08:00')
        stop_mins = int(request.POST.get('stop_mins', 15))
        
        addresses = request.POST.getlist('address[]')
        priorities = request.POST.getlist('priority[]')
        types = request.POST.getlist('type[]')
        titles = request.POST.getlist('title[]')
        descs = request.POST.getlist('desc[]')
        tags_list = request.POST.getlist('tags[]')
        is_treasures = request.POST.getlist('is_treasure[]')
        treasure_reasons = request.POST.getlist('treasure_reason[]')
        is_wishlist_matches = request.POST.getlist('is_wishlist_match[]')
        match_reasons = request.POST.getlist('match_reason[]')
        is_community_events = request.POST.getlist('is_community_event[]')
        
        destinations: List[Dict[str, Any]] = []
        for i in range(len(addresses)):
            addr = addresses[i].strip()
            if addr:
                prio = int(priorities[i]) if i < len(priorities) and priorities[i].strip() else 0
                ty = types[i] if i < len(types) and types[i] else 'garage'
                
                try:
                    tags = json.loads(tags_list[i]) if i < len(tags_list) else []
                except Exception:
                    tags = []

                destinations.append({
                    'address': addr, 
                    'priority': prio, 
                    'type': ty,
                    'title': titles[i] if i < len(titles) else '',
                    'desc': descs[i] if i < len(descs) else '',
                    'tags': tags,
                    'is_treasure': is_treasures[i] == 'true' if i < len(is_treasures) else False,
                    'treasure_reason': treasure_reasons[i] if i < len(treasure_reasons) else '',
                    'is_wishlist_match': is_wishlist_matches[i] == 'true' if i < len(is_wishlist_matches) else False,
                    'match_reason': match_reasons[i] if i < len(match_reasons) else '',
                    'is_community_event': is_community_events[i] == 'true' if i < len(is_community_events) else False
                })
                
        request.session['start_address'] = start_address
        request.session['other_addresses'] = destinations
        request.session['start_time'] = start_time
        request.session['stop_mins'] = stop_mins
        
        # CLEAR DISCOVERY CACHE: The user has committed to a route
        request.session.pop('discovery_cache_key', None)
        request.session.pop('discovery_results', None)
        
        return HttpResponseRedirect(reverse('results'))


class ResultsView(LoginRequiredMixin, View):
    template_name: str = 'RouteFinderWeb/route.html'

    def get(self, request: HttpRequest) -> HttpResponse:
        start_address = request.session.get('start_address')
        other_addresses = request.session.get('other_addresses')

        if not start_address or not other_addresses:
            return HttpResponseRedirect(reverse('main'))

        return render(request, self.template_name, {
            'start_address': start_address,
            'other_addresses': other_addresses,
            'GOOGLE_MAPS_API_KEY': getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
        })

class RouteDataView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> JsonResponse:
        start_address = request.session.get('start_address')
        other_addresses = request.session.get('other_addresses')

        if not start_address or not other_addresses:
            return JsonResponse({'success': False, 'error': 'Missing route parameters'}, status=400)

        api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
        if not api_key and not getattr(settings, 'MOCK_MODE', False):
            return JsonResponse({'success': False, 'error': 'API Key not configured'}, status=500)

        try:
            solver = RouteSolver(api_key)
            optimized_route = solver.solve(start_address, other_addresses)
            
            start_time_str = request.session.get('start_time', '08:00')
            stop_mins = int(request.session.get('stop_mins', 15))
            
            start_dt = datetime.datetime.strptime(start_time_str, "%H:%M")
            current_time = start_dt
            
            # Map metadata back to optimized route
            metadata_map = {item['address']: item for item in other_addresses}
            
            historic_ratings: Dict[str, str] = {}
            all_addrs = [item['address'] for item in optimized_route] + [start_address]
            ratings_qs = AddressRating.objects.filter(user=request.user, address__in=all_addrs)
            for rq in ratings_qs:
                historic_ratings[rq.address] = rq.rating

            final_itinerary: List[Dict[str, Any]] = []
            # Start at Origin
            final_itinerary.append({
                'address': start_address,
                'arrival_time': 'Start',
                'departure_time': current_time.strftime("%I:%M %p"),
                'drive_time_str': 'Origin',
                'is_start': True,
                'rating': historic_ratings.get(start_address, 'neutral'),
                'type': 'home'
            })

            for stop in optimized_route:
                meta = metadata_map.get(stop['address'], {})
                
                # Travel
                current_time += datetime.timedelta(seconds=stop.get('duration_sec', stop.get('drive_time_seconds', 0)))
                arrival_str = current_time.strftime("%I:%M %p")
                
                # Stop
                duration = stop_mins * 3 if meta.get('is_community_event') else stop_mins
                current_time += datetime.timedelta(minutes=duration)
                departure_str = current_time.strftime("%I:%M %p")
                
                final_itinerary.append({
                    'address': stop['address'],
                    'arrival_time': arrival_str,
                    'departure_time': departure_str,
                    'drive_time_str': stop.get('duration_text', f"{stop.get('drive_time_seconds', 0)//60} mins"),
                    'is_start': False,
                    'rating': historic_ratings.get(stop['address'], 'neutral'),
                    'title': meta.get('title', ''),
                    'desc': meta.get('desc', ''),
                    'tags': meta.get('tags', []),
                    'is_treasure': meta.get('is_treasure', False),
                    'treasure_reason': meta.get('treasure_reason', ''),
                    'is_wishlist_match': meta.get('is_wishlist_match', False),
                    'match_reason': meta.get('match_reason', '')
                })

            maps_urls = generate_google_maps_urls(final_itinerary)
            
            # MISSION ACCOMPLISHED: Clear 'The Vault' (Saved Intel) once a route is executed/finalized
            ScoutIntel.objects.filter(user=request.user).delete()
            
            return JsonResponse({
                'success': True, 
                'itinerary': final_itinerary,
                'google_maps_urls': maps_urls
            })
        except Exception as e:
            logger.exception("Failed to calculate route data")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    def post(self, request: HttpRequest) -> HttpResponse:
        # Allow new search from results page
        form = forms.AddressForm(request.POST)
        if form.is_valid():
            request.session['start_address'] = form.cleaned_data['start']
            request.session['other_addresses'] = form.cleaned_data['addresses']
            return HttpResponseRedirect(reverse('results'))
            
        return HttpResponseRedirect(reverse('index'))

class RemoveAddressView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            data = json.loads(request.body)
            address = data.get('address')
            
            if not address:
                return JsonResponse({'error': 'Missing address'}, status=400)
                
            other_addresses = request.session.get('other_addresses', [])
            
            new_list: List[Dict[str, Any]] = []
            for item in other_addresses:
                if isinstance(item, dict):
                    if item.get('address') != address:
                        new_list.append(item)
                elif item != address:
                    new_list.append({'address': item, 'priority': 0, 'type': 'garage'})
            
            request.session['other_addresses'] = new_list
            request.session['other_addresses_raw'] = json.dumps(new_list)
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

class ClearRouteView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            request.session['other_addresses'] = []
            request.session['other_addresses_raw'] = '[]'
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
