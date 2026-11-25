from typing import Any, Dict, List, Optional
import requests
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self, user: Any = None) -> None:
        self.user = user
        self.ai_enabled = True
        self.thinking_enabled = False
        self.thinking_effort = 50
        self.ai_provider = 'ollama'
        self.api_key = ''
        
        # Load user profile settings if available, else use defaults from settings
        profile = getattr(user, 'userprofile', None) if user else None
        
        if profile:
            self.ai_enabled = getattr(profile, 'ai_enabled', True)
            self.thinking_enabled = getattr(profile, 'ai_thinking_enabled', False)
            self.thinking_effort = getattr(profile, 'ai_thinking_effort', 50)
            self.ai_provider = getattr(profile, 'ai_provider', 'ollama')
            
            # API URL Configuration
            profile_url = getattr(profile, 'ai_api_url', '').strip()
            if profile_url:
                self.base_url = profile_url
            else:
                if self.ai_provider == 'openai':
                    self.base_url = 'https://api.openai.com/v1'
                else:
                    self.base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://host.docker.internal:11434')
            
            # Model Configuration
            profile_model = getattr(profile, 'ai_model', '').strip()
            if profile_model:
                self.model = profile_model
            else:
                if self.ai_provider == 'openai':
                    self.model = 'gpt-4o'
                else:
                    self.model = getattr(settings, 'OLLAMA_MODEL', 'gemma:4b')
            
            # API Key Configuration
            self.api_key = getattr(profile, 'ai_api_key', '')
        else:
            self.base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://host.docker.internal:11434')
            self.model = getattr(settings, 'OLLAMA_MODEL', 'gemma:4b')

    @staticmethod
    def _normalize_v1_base(url: str) -> str:
        clean = (url or '').strip().rstrip('/')
        if clean.endswith('/v1'):
            clean = clean[:-3]
        return clean

    @classmethod
    def test_connection(cls, base_url: str, api_key: str = '') -> Dict[str, Any]:
        """Test an OpenAI-compatible endpoint via GET /v1/models and return available model IDs."""
        root = cls._normalize_v1_base(base_url)
        if not root:
            return {'ok': False, 'error': 'API Base URL is required.', 'models': []}
        headers: Dict[str, str] = {}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        try:
            resp = requests.get(f'{root}/v1/models', headers=headers, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            models = sorted(
                m['id'] for m in payload.get('data', []) if isinstance(m, dict) and m.get('id')
            )
            return {'ok': True, 'models': models}
        except Exception as e:
            logger.warning(f"AI connection test failed for {root}: {e}")
            return {'ok': False, 'error': str(e), 'models': []}

    def _call_raw(self, prompt: str, timeout: int = 50) -> Any:
        """Executes raw HTTP calls to Ollama or OpenAI with settings and custom thinking options."""
        if not self.ai_enabled:
            return None

        if getattr(settings, 'MOCK_MODE', False):
            logger.info("MOCK_MODE: Mocking AI service raw call")
            prompt_lower = prompt.lower()
            if "garage sale description" in prompt_lower or "keys: 'tags', 'is_treasure'" in prompt_lower:
                import re
                count = len(re.findall(r'\d+\.\s', prompt))
                if count == 0:
                    count = 1
                return [
                    {
                        "tags": ["#Furniture", "#MovingSale"],
                        "is_treasure": True,
                        "treasure_reason": "High-value vintage furniture items detected.",
                        "is_bust_candidate": False,
                        "bust_reason": "",
                        "is_wishlist_match": True,
                        "match_reason": "Matched 'vintage furniture' on wishlist.",
                        "is_moving_sale": True,
                        "is_potential_goldmine": True,
                        "profit_rating": "High",
                        "profit_reason": "Moving sale with lots of furniture."
                    } for _ in range(count)
                ]
            elif "thrift stores" in prompt_lower:
                import re
                count = len(re.findall(r'\d+\.\s', prompt))
                if count == 0:
                    count = 1
                return [
                    {
                        "tags": ["#Thrift", "#Goodwill"],
                        "is_potential_goldmine": True,
                        "profit_rating": "Medium",
                        "profit_reason": "Highly rated thrift store."
                    } for _ in range(count)
                ]
            elif "is_bust_candidate" in prompt_lower:
                return {"is_bust_candidate": False}
            elif "neighborhood/community clusters" in prompt_lower or "clusters" in prompt_lower:
                return {
                    "clusters": [
                        {"name": "Springfield Subdivision", "indices": [0, 1]}
                    ]
                }
            return {}

        # Build prompt override if thinking is enabled
        if self.thinking_enabled:
            prompt = f"[System instruction: Perform detailed logical reasoning with an effort level of {self.thinking_effort}% before returning the final response]\n{prompt}"

        # Standard OpenAI-Compatible Payload & Routing (works for Ollama, OpenAI, OpenRouter, LM Studio, vLLM, etc.)
        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }

        if self.thinking_enabled:
            temp = round(max(0.1, min(1.0, 1.0 - (self.thinking_effort / 100.0))), 2)
            payload["temperature"] = temp

        url = self.base_url.strip()
        if not (url.endswith('/chat/completions') or url.endswith('/completions')):
            url = f"{self._normalize_v1_base(url)}/v1/chat/completions"

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout
            )
            if response.status_code == 200:
                result_data = response.json()
                result_text = result_data['choices'][0]['message']['content']
                return json.loads(result_text)
            else:
                logger.error(f"OpenAI compatible API returned status code {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"OpenAI compatible API Call Error: {e}")
        return None

    def _call_ollama(self, prompt: str, timeout: int = 50) -> List[Dict[str, Any]]:
        """Shared logic for calling Ollama and adapting JSON responses into lists."""
        analysis = self._call_raw(prompt, timeout)
        if not analysis:
            return []
            
        # ADAPTATION: Handle dict wrapper vs list
        if isinstance(analysis, dict):
            for key in ['listings', 'results', 'data', 'analysis', 'items', 'clusters']:
                if key in analysis and isinstance(analysis[key], list):
                    return analysis[key]
            for val in analysis.values():
                if isinstance(val, list):
                    return val
        return analysis if isinstance(analysis, list) else []

    def analyze_thrift_batch(self, stores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Specialized analysis for thrift stores with parallel chunking."""
        if not self.ai_enabled or not stores:
            return [{
                "tags": ["#Thrift"], 
                "is_potential_goldmine": False, 
                "profit_rating": "None",
                "profit_reason": ""
            } for _ in stores]
        
        results: List[Dict[str, Any]] = []
        chunk_size = 10
        chunks = [stores[i:i+chunk_size] for i in range(0, len(stores), chunk_size)]
        
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            def process_chunk(chunk: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                prompt = (
                    "Analyze these thrift stores and return a JSON array of objects.\n"
                    "Keys: 'tags' (list), 'is_potential_goldmine' (bool), 'profit_rating' (High/Medium/None), 'profit_reason'.\n"
                    "STORES:\n"
                )
                for j, s in enumerate(chunk):
                    prompt += f"{j+1}. {s['title']} at {s['address']}\n"
                
                analysis = self._call_ollama(prompt, timeout=40)
                
                # Hardening: Filter out non-dict items
                if isinstance(analysis, list):
                    analysis = [item for item in analysis if isinstance(item, dict)]
                else:
                    analysis = []
                    
                while len(analysis) < len(chunk):
                    analysis.append({
                        "tags": ["#Thrift"], 
                        "is_potential_goldmine": False, 
                        "profit_rating": "None",
                        "profit_reason": ""
                    })
                return analysis[:len(chunk)]
            
            future_results = list(executor.map(process_chunk, chunks))
            for res in future_results:
                results.extend(res)
                
        return results

    def analyze_listings_batch(self, listings: List[str], bust_history: Optional[List[str]] = None, wishlist: Optional[str] = None) -> List[Dict[str, Any]]:
        """Enriches garage sales with tactical analysis using parallel chunking."""
        if not self.ai_enabled or not listings:
            return [{
                "tags": [], "is_treasure": False, "is_bust_candidate": False,
                "is_wishlist_match": False, "is_moving_sale": False, 
                "is_potential_goldmine": False, "profit_rating": "None",
                "treasure_reason": "", "bust_reason": "", "match_reason": "", "profit_reason": ""
            } for _ in listings]
        
        results: List[Dict[str, Any]] = []
        chunk_size = 8
        chunks = [listings[i:i+chunk_size] for i in range(0, len(listings), chunk_size)]
        
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            def process_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
                prompt = (
                    "Analyze these garage sale descriptions and return a JSON array of objects.\n"
                    "Keys: 'tags', 'is_treasure' (bool), 'treasure_reason', 'is_bust_candidate' (bool), 'bust_reason', "
                    "'is_wishlist_match' (bool), 'match_reason', 'is_moving_sale' (bool), 'is_potential_goldmine' (bool), "
                    "'profit_rating' (High/Medium/None), 'profit_reason'.\n"
                )
                
                if bust_history:
                    prompt += "USER BUST HISTORY (Dislikes):\n"
                    for h in bust_history[:2]: prompt += f"- {h}\n"
                if wishlist:
                    prompt += f"USER WISHLIST: {wishlist}\n"
                
                prompt += "\nDESCRIPTIONS:\n"
                for j, desc in enumerate(chunk):
                    prompt += f"{j+1}. {desc[:400]}\n"
                
                analysis = self._call_ollama(prompt, timeout=50)
                
                # Clean and Pad (Hardening: Filter out non-dict items)
                if isinstance(analysis, list):
                    analysis = [item for item in analysis if isinstance(item, dict)]
                else:
                    analysis = []
                    
                for item in analysis:
                    if 'tags' in item and isinstance(item['tags'], str):
                        item['tags'] = [t.strip() for t in item['tags'].split(',')]
                        
                while len(analysis) < len(chunk):
                    analysis.append({
                        "tags": [], "is_treasure": False, "is_bust_candidate": False,
                        "is_wishlist_match": False, "is_moving_sale": False, 
                        "is_potential_goldmine": False, "profit_rating": "None",
                        "treasure_reason": "", "bust_reason": "", "match_reason": "", "profit_reason": ""
                    })
                return analysis[:len(chunk)]

            future_results = list(executor.map(process_chunk, chunks))
            for res in future_results:
                results.extend(res)
                
        return results

    def predict_bust_suitability(self, description: str, bust_history: List[str]) -> bool:
        """
        Compares a single listing against the user's history of 'Bust' sales.
        Returns a boolean (True if it looks like a bust).
        """
        if not self.ai_enabled or not bust_history:
            return False

        prompt = (
            "The user dislikes certain garage sales. Here are descriptions of sales they marked as a 'Bust':\n"
        )
        for history in bust_history:
            prompt += f"- {history}\n"
            
        prompt += (
            f"\nNow analyze this new listing: \"{description[:400]}\"\n"
            "Does this new listing share the same negative characteristics as the Bust history? "
            "(e.g. if history is all 'baby clothes' and this is 'infant wear', it's a match).\n"
            "Return ONLY a JSON object with a key 'is_bust_candidate' (boolean)."
        )

        result = self._call_raw(prompt, timeout=15)
        if isinstance(result, dict):
            return result.get('is_bust_candidate', False)
        return False

    def cluster_neighborhoods(self, titles: List[str]) -> List[Dict[str, Any]]:
        """
        Groups a list of titles into neighborhood/community clusters using AI.
        Returns a list of cluster objects: {"name": "Neighborhood Name", "indices": [0, 2, 5]}
        """
        if not self.ai_enabled or not titles:
            return []

        prompt = (
            "You are a local community expert. Analyze these garage sale titles and group them into 'Neighborhood/Community Clusters' ONLY if they are part of the same shared event.\n\n"
            "RULES:\n"
            "1. Ignore broad geographic names that appear in many unrelated listings (e.g. 'Chapel Hill', 'Durham').\n"
            "2. Look for specific subdivision or neighborhood names (e.g. 'Churton Grove', 'Oak Creek').\n"
            "3. If multiple listings share the same specific neighborhood name, cluster them.\n"
            "4. Return a JSON object with a 'clusters' key, which is an array of objects: {'name': 'Specific Neighborhood Name', 'indices': [0-based indices from the list]}.\n"
            "5. If a listing doesn't belong to any cluster, do not include it in any 'indices'.\n\n"
            "TITLES TO ANALYZE:\n"
        )
        
        for i, title in enumerate(titles):
            prompt += f"{i}. {title}\n"

        result = self._call_raw(prompt, timeout=30)
        if isinstance(result, dict):
            return result.get('clusters', [])
        return []

