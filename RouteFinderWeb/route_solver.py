import logging
import time
from typing import Any, Dict, List
import googlemaps
from django.conf import settings

logger = logging.getLogger(__name__)

class RouteSolver:
    def __init__(self, api_key: str) -> None:
        self.mock_mode = getattr(settings, 'MOCK_MODE', False)
        if not self.mock_mode and api_key:
            self.gmaps = googlemaps.Client(key=api_key)
        else:
            self.gmaps = None

    def solve(self, start_address: str, addresses_data: List[Dict[str, Any]], return_to_start: bool = True) -> List[Dict[str, Any]]:
        """
        Solves the TSP for the given addresses across defined priority tiers.
        Optionally includes a final leg back to the start_address.
        """
        import collections
        start_time = time.time()
        logger.info(
            f"Solving route starting from '{start_address}' with {len(addresses_data)} waypoint(s), return_to_start={return_to_start}",
            extra={"action": "route.solve"}
        )
        buckets = collections.defaultdict(list)
        type_lookup = {start_address: 'home'}
        
        for item in addresses_data:
            prio = int(item.get('priority', 0))
            addr = item['address']
            buckets[prio].append(addr)
            type_lookup[addr] = item.get('type', 'garage')
            
        # determine order of bucket keys: 1, 2, 3... then 0
        keys = sorted([k for k in buckets.keys() if k > 0])
        if 0 in buckets:
            keys.append(0)
            
        optimized_route: List[Dict[str, Any]] = []
        current_start = start_address
        
        for k in keys:
            bucket_addrs = buckets[k]
            if not bucket_addrs:
                continue
                
            all_addrs = [current_start] + bucket_addrs
            distance_matrix = self._get_distance_matrix(all_addrs)
            route_indices = self._solve_tsp(distance_matrix)
            
            for step in range(1, len(route_indices)): # skip 0 which is current_start
                cur_node = route_indices[step]
                addr = all_addrs[cur_node]
                
                prev_node = route_indices[step-1]
                drive_secs = distance_matrix[prev_node][cur_node]
                
                optimized_route.append({
                    'address': addr,
                    'drive_time_seconds': drive_secs,
                    'priority': k,
                    'type': type_lookup.get(addr, 'garage')
                })
                
            last_idx = route_indices[-1]
            current_start = all_addrs[last_idx]
            
        # Optional: Add return leg back to home base
        if return_to_start and optimized_route:
            last_stop = optimized_route[-1]['address']
            # Quick one-off distance matrix for the return leg
            return_matrix = self._get_distance_matrix([last_stop, start_address])
            return_drive_secs = return_matrix[0][1]
            
            optimized_route.append({
                'address': start_address,
                'drive_time_seconds': return_drive_secs,
                'priority': 'Home',
                'type': 'home_return'
            })
            
        duration = round((time.time() - start_time) * 1000, 2)
        total_drive_time = sum(stop.get('drive_time_seconds', 0) for stop in optimized_route)
        logger.info(
            f"Route solved successfully: {len(optimized_route)} stops, total drive time ~{round(total_drive_time/60, 1)}m, calculated in {duration}ms",
            extra={"action": "route.solve"}
        )
        return optimized_route

    def _get_distance_matrix(self, locations: List[str]) -> List[List[float]]:
        """
        Fetches the distance matrix from Google Maps API.
        Returns a 2D list of distances (in seconds).
        """
        if self.mock_mode or not self.gmaps:
            logger.debug(f"RouteSolver: generating mock distance matrix for {len(locations)} locations", extra={"action": "route.matrix_mock"})
            # Generate a mock distance matrix: 5 minutes (300 seconds) between each unique pair
            matrix: List[List[float]] = []
            for i in range(len(locations)):
                row: List[float] = []
                for j in range(len(locations)):
                    if i == j:
                        row.append(0.0)
                    else:
                        row.append(300.0)
                matrix.append(row)
            return matrix

        matrix = []
        logger.debug(f"Requesting Google Maps Distance Matrix for {len(locations)} locations", extra={"action": "route.matrix_api"})
        result = self.gmaps.distance_matrix(locations, locations, mode="driving", units="imperial")
        
        if result.get('status') != 'OK':
            err_msg = f"Error fetching distance matrix from Google Maps: status={result.get('status')} error_message={result.get('error_message')}"
            logger.error(err_msg, extra={"action": "route.matrix_api"})
            raise Exception(err_msg)

        rows = result['rows']
        for row in rows:
            row_distances = []
            for element in row['elements']:
                if element['status'] == 'OK':
                    # Use duration value (seconds) for optimization
                    row_distances.append(float(element['duration']['value']))
                else:
                    # If route not found, use a very large number
                    row_distances.append(float('inf'))
            matrix.append(row_distances)
            
        return matrix

    def _solve_tsp(self, distance_matrix: List[List[float]]) -> List[int]:
        """
        Implements 2-Opt heuristic to find a near-optimal route.
        """
        num_points = len(distance_matrix)
        route = list(range(num_points))
        
        improved = True
        while improved:
            improved = False
            for i in range(1, num_points - 1):
                for j in range(i + 1, num_points):
                    if j - i == 1: continue # No change for adjacent edges
                    
                    new_route = route[:]
                    # Reverse the segment between i and j
                    new_route[i:j] = route[j-1:i-1:-1]
                    
                    if self._calculate_total_distance(new_route, distance_matrix) < self._calculate_total_distance(route, distance_matrix):
                        route = new_route
                        improved = True
                        
        return route

    def _calculate_total_distance(self, route: List[int], distance_matrix: List[List[float]]) -> float:
        total_dist = 0.0
        for i in range(len(route) - 1):
            from_idx = route[i]
            to_idx = route[i+1]
            val = distance_matrix[from_idx][to_idx]
            # Handle infinity safely
            if val == float('inf'):
                total_dist += 999999.0
            else:
                total_dist += val
        return total_dist

