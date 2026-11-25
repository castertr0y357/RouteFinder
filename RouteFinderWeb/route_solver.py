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
        
        for idx_k, k in enumerate(keys):
            bucket_addrs = buckets[k]
            if not bucket_addrs:
                continue

            is_last_bucket = (idx_k == len(keys) - 1)
            all_addrs = [current_start] + bucket_addrs
            return_node = None
            if is_last_bucket and return_to_start:
                if start_address == current_start:
                    return_node = 0
                else:
                    all_addrs.append(start_address)
                    return_node = len(all_addrs) - 1

            distance_matrix = self._get_distance_matrix(all_addrs)
            visit_count = len(bucket_addrs) + 1  # node 0 + bucket_addrs
            route_indices = self._solve_tsp(distance_matrix, num_visit=visit_count, return_node=return_node)
            
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
            
            if is_last_bucket and return_to_start and return_node is not None:
                return_drive_secs = distance_matrix[last_idx][return_node]
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

    def _edge_cost(self, distance_matrix: List[List[float]], u: int, v: int) -> float:
        val = distance_matrix[u][v]
        return 999999.0 if val == float('inf') else float(val)

    def _solve_tsp(self, distance_matrix: List[List[float]], num_visit: int = 0, return_node: Any = None) -> List[int]:
        """
        Finds the optimal route starting at node 0 and visiting nodes 1..num_visit-1.
        Uses exact Held-Karp Dynamic Programming for <= 13 stops, and Nearest-Neighbor + 2-Opt for larger sets.
        """
        n = num_visit if num_visit > 0 else len(distance_matrix)
        if n <= 1:
            return list(range(n))
        if n == 2:
            return [0, 1]

        if n <= 14:
            return self._solve_held_karp(distance_matrix, n, return_node)
        return self._solve_2opt(distance_matrix, n, return_node)

    def _solve_held_karp(self, distance_matrix: List[List[float]], n: int, return_node: Any = None) -> List[int]:
        """Exact Held-Karp DP solver for nodes 1..n-1 starting from node 0."""
        num_stops = n - 1
        full_mask = (1 << num_stops) - 1
        # dp[mask][last_stop_idx] where last_stop_idx is 0..num_stops-1 (representing node last_stop_idx + 1)
        dp: Dict[int, List[float]] = {}
        parent: Dict[int, List[int]] = {}

        for i in range(num_stops):
            mask = 1 << i
            dp[mask] = [float('inf')] * num_stops
            parent[mask] = [-1] * num_stops
            dp[mask][i] = self._edge_cost(distance_matrix, 0, i + 1)

        for mask in range(1, full_mask + 1):
            if mask not in dp:
                continue
            cur_costs = dp[mask]
            for last in range(num_stops):
                cost_so_far = cur_costs[last]
                if cost_so_far == float('inf'):
                    continue
                u = last + 1
                for nxt in range(num_stops):
                    if mask & (1 << nxt):
                        continue
                    nxt_mask = mask | (1 << nxt)
                    if nxt_mask not in dp:
                        dp[nxt_mask] = [float('inf')] * num_stops
                        parent[nxt_mask] = [-1] * num_stops
                    new_cost = cost_so_far + self._edge_cost(distance_matrix, u, nxt + 1)
                    if new_cost < dp[nxt_mask][nxt]:
                        dp[nxt_mask][nxt] = new_cost
                        parent[nxt_mask][nxt] = last

        best_cost = float('inf')
        best_last = 0
        for last in range(num_stops):
            total = dp[full_mask][last]
            if return_node is not None:
                total += self._edge_cost(distance_matrix, last + 1, return_node)
            if total < best_cost:
                best_cost = total
                best_last = last

        # Reconstruct path
        rev_stops: List[int] = []
        cur_mask = full_mask
        cur_last = best_last
        while cur_last != -1:
            rev_stops.append(cur_last + 1)
            prev_last = parent[cur_mask][cur_last]
            cur_mask ^= (1 << cur_last)
            cur_last = prev_last

        rev_stops.reverse()
        return [0] + rev_stops

    def _solve_2opt(self, distance_matrix: List[List[float]], n: int, return_node: Any = None) -> List[int]:
        """Nearest-Neighbor initialization followed by full-range 2-Opt local search."""
        unvisited = set(range(1, n))
        route = [0]
        while unvisited:
            last = route[-1]
            nxt = min(unvisited, key=lambda x: self._edge_cost(distance_matrix, last, x))
            route.append(nxt)
            unvisited.remove(nxt)

        improved = True
        while improved:
            improved = False
            best_dist = self._calculate_total_distance(route, distance_matrix, return_node)
            for i in range(1, n - 1):
                for j in range(i + 2, n + 1):
                    new_route = route[:]
                    new_route[i:j] = route[j - 1:i - 1:-1]
                    new_dist = self._calculate_total_distance(new_route, distance_matrix, return_node)
                    if new_dist < best_dist:
                        route = new_route
                        best_dist = new_dist
                        improved = True
        return route

    def _calculate_total_distance(self, route: List[int], distance_matrix: List[List[float]], return_node: Any = None) -> float:
        total_dist = 0.0
        for i in range(len(route) - 1):
            total_dist += self._edge_cost(distance_matrix, route[i], route[i + 1])
        if return_node is not None and route:
            total_dist += self._edge_cost(distance_matrix, route[-1], return_node)
        return total_dist

