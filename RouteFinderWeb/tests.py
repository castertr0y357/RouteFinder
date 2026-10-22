from django.test import TestCase
from unittest.mock import MagicMock, patch
from .route_solver import RouteSolver

class RouteSolverTests(TestCase):
    def setUp(self):
        self.api_key = "test_key"
        self.start_address = "Start"
        self.other_addresses = [
            {'address': 'A', 'priority': 0, 'type': 'garage'},
            {'address': 'B', 'priority': 0, 'type': 'garage'},
            {'address': 'C', 'priority': 0, 'type': 'garage'}
        ]

    @patch('googlemaps.Client')
    def test_solve_tsp(self, mock_gmaps):
        # Mock the distance matrix response
        solver = RouteSolver(self.api_key)
        
        matrix = [
            [0, 10, 100, 100], # 0
            [10, 0, 10, 100],  # 1
            [100, 10, 0, 10],  # 2
            [100, 100, 10, 0]  # 3
        ]
        
        solver._get_distance_matrix = MagicMock(return_value=matrix)
        
        route = solver.solve(self.start_address, self.other_addresses, return_to_start=False)
        
        # Expected order: A, B, C
        self.assertEqual([item['address'] for item in route], ["A", "B", "C"])

    @patch('googlemaps.Client')
    def test_solve_tsp_2opt_swap(self, mock_gmaps):
        # Test a case where a swap is needed
        solver = RouteSolver(self.api_key)
        
        # Matrix must match input order: [Start, B, A, C]
        matrix = [
            [0,   100, 10,  100], # Start
            [100, 0,   10,  10],  # B
            [10,  10,  0,   100], # A
            [100, 10,  100, 0]    # C
        ]
        solver._get_distance_matrix = MagicMock(return_value=matrix)
        
        input_addresses = [
            {'address': 'B', 'priority': 0, 'type': 'garage'},
            {'address': 'A', 'priority': 0, 'type': 'garage'},
            {'address': 'C', 'priority': 0, 'type': 'garage'}
        ]
        route = solver.solve("Start", input_addresses, return_to_start=False)
        
        self.assertEqual([item['address'] for item in route], ["A", "B", "C"])

from django.contrib.auth.models import User
from .ai_service import AIService

class AIServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.profile = self.user.userprofile

    @patch('requests.post')
    def test_ai_disabled(self, mock_post):
        self.profile.ai_enabled = False
        self.profile.save()
        
        ai = AIService(user=self.user)
        self.assertFalse(ai.ai_enabled)
        
        # Test listings batch enrichment
        listings = ["Nice garage sale in Chapel Hill", "Selling baby clothes"]
        results = ai.analyze_listings_batch(listings)
        
        # Requests should not be made
        mock_post.assert_not_called()
        # Fallback values returned
        self.assertEqual(len(results), len(listings))
        for r in results:
            self.assertFalse(r['is_treasure'])
            self.assertFalse(r['is_bust_candidate'])
            self.assertEqual(r['tags'], [])

    @patch('requests.post')
    def test_ai_thinking_payload(self, mock_post):
        self.profile.ai_enabled = True
        self.profile.ai_thinking_enabled = True
        self.profile.ai_thinking_effort = 80
        self.profile.save()
        
        ai = AIService(user=self.user)
        self.assertTrue(ai.ai_enabled)
        self.assertTrue(ai.thinking_enabled)
        self.assertEqual(ai.thinking_effort, 80)
        
        # Mock successful JSON response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": '{"is_bust_candidate": true}'}
        mock_post.return_value = mock_resp
        
        # Perform query
        is_bust = ai.predict_bust_suitability("Baby stuff", ["Marked baby stuff as bust"])
        
        # Verify requests.post called with correct thinking parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        payload = kwargs['json']
        
        self.assertTrue(payload['think'])
        self.assertEqual(payload['options']['temperature'], 0.2) # 1 - 80/100 = 0.2
        self.assertEqual(payload['thinking_budget'], 800)
        self.assertIn("Perform detailed logical reasoning with an effort level of 80%", payload['prompt'])

    @patch('requests.post')
    def test_openai_payload(self, mock_post):
        self.profile.ai_enabled = True
        self.profile.ai_provider = 'openai'
        self.profile.ai_api_url = 'https://custom-openai-api.com/v1/'
        self.profile.ai_model = 'gpt-4o-custom'
        self.profile.ai_api_key = 'test-key-123'
        self.profile.ai_thinking_enabled = True
        self.profile.ai_thinking_effort = 50
        self.profile.save()

        ai = AIService(user=self.user)
        self.assertEqual(ai.ai_provider, 'openai')
        self.assertEqual(ai.base_url, 'https://custom-openai-api.com/v1/')
        self.assertEqual(ai.model, 'gpt-4o-custom')
        self.assertEqual(ai.api_key, 'test-key-123')

        # Mock OpenAI response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"is_bust_candidate": false}'
                }
            }]
        }
        mock_post.return_value = mock_resp

        # Perform query
        is_bust = ai.predict_bust_suitability("Baby stuff", ["Marked baby stuff as bust"])
        self.assertFalse(is_bust)

        # Verify requests.post called with correct OpenAI URL and headers
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        
        self.assertEqual(args[0], 'https://custom-openai-api.com/v1/chat/completions')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-key-123')
        
        payload = kwargs['json']
        self.assertEqual(payload['model'], 'gpt-4o-custom')
        self.assertEqual(payload['messages'][0]['role'], 'user')
        self.assertEqual(payload['response_format'], {"type": "json_object"})
        self.assertEqual(payload['temperature'], 0.5)



class SaleDiscoveryViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

    def test_discover_page_renders(self):
        response = self.client.get('/discover/')
        self.assertEqual(response.status_code, 200)


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser@example.com", email="testuser@example.com", password="password")
        self.client.login(username="testuser@example.com", password="password")

    def test_profile_page_renders_fields(self):
        response = self.client.get('/profile/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id_ai_provider')
        self.assertContains(response, 'id_ai_api_url')
        self.assertContains(response, 'id_ai_model')







class DatabaseConfigTests(TestCase):
    def test_database_url_postgresql(self):
        import environ
        from RouteFinder.settings import get_database_config
        env_mock = environ.Env()
        with patch.dict('os.environ', {'DATABASE_URL': 'postgres://testuser:testpass@db.example.com:5432/testdb'}):
            config = get_database_config(env_mock, '/tmp')
            self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
            self.assertEqual(config['NAME'], 'testdb')
            self.assertEqual(config['USER'], 'testuser')
            self.assertEqual(config['PASSWORD'], 'testpass')
            self.assertEqual(config['HOST'], 'db.example.com')
            self.assertEqual(config['PORT'], 5432)

    def test_database_url_sqlite(self):
        import environ
        from RouteFinder.settings import get_database_config
        env_mock = environ.Env()
        with patch.dict('os.environ', {'DATABASE_URL': 'sqlite:///custom.sqlite3'}):
            config = get_database_config(env_mock, '/tmp')
            self.assertEqual(config['ENGINE'], 'django.db.backends.sqlite3')
            self.assertIn('custom.sqlite3', config['NAME'])

    def test_individual_postgres_env_vars(self):
        import environ
        from RouteFinder.settings import get_database_config
        env_mock = environ.Env()
        env_vars = {
            'DATABASE_HOST': 'postgres.internal',
            'POSTGRES_DB': 'my_routefinder',
            'POSTGRES_USER': 'pg_admin',
            'POSTGRES_PASSWORD': 'supersecretpass',
            'DATABASE_PORT': '5433',
        }
        with patch.dict('os.environ', env_vars, clear=True):
            config = get_database_config(env_mock, '/tmp')
            self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
            self.assertEqual(config['NAME'], 'my_routefinder')
            self.assertEqual(config['USER'], 'pg_admin')
            self.assertEqual(config['PASSWORD'], 'supersecretpass')
            self.assertEqual(config['HOST'], 'postgres.internal')
            self.assertEqual(config['PORT'], '5433')

    def test_unexpanded_k8s_template_falls_back_to_individual_postgres_vars(self):
        import environ
        from RouteFinder.settings import get_database_config
        env_mock = environ.Env()
        env_vars = {
            'DATABASE_URL': 'postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(DATABASE_HOST):$(DATABASE_PORT)/$(POSTGRES_DB)',
            'DATABASE_HOST': 'db',
            'POSTGRES_DB': 'routefinder',
            'POSTGRES_USER': 'postgres',
            'POSTGRES_PASSWORD': 'pgpass',
            'DATABASE_PORT': '5432',
        }
        with patch.dict('os.environ', env_vars, clear=True):
            config = get_database_config(env_mock, '/tmp')
            self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
            self.assertEqual(config['NAME'], 'routefinder')
            self.assertEqual(config['USER'], 'postgres')
            self.assertEqual(config['HOST'], 'db')

    def test_zero_config_fallback_to_sqlite(self):
        import environ
        from RouteFinder.settings import get_database_config
        env_mock = environ.Env()
        with patch.dict('os.environ', {}, clear=True):
            config = get_database_config(env_mock, '/tmp/base')
            self.assertEqual(config['ENGINE'], 'django.db.backends.sqlite3')
            self.assertIn('db.sqlite3', config['NAME'])

    def test_pgpassword_env_var(self):
        import environ
        from RouteFinder.settings import get_database_config
        env_mock = environ.Env()
        env_vars = {
            'DATABASE_HOST': 'routefinder-db',
            'PGPASSWORD': 'pgpass_from_env',
        }
        with patch.dict('os.environ', env_vars, clear=True):
            config = get_database_config(env_mock, '/tmp')
            self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
            self.assertEqual(config['PASSWORD'], 'pgpass_from_env')
            self.assertEqual(config['HOST'], 'routefinder-db')

    def test_database_url_backfills_postgres_password(self):
        import environ
        from RouteFinder.settings import get_database_config
        env_mock = environ.Env()
        env_vars = {
            'DATABASE_URL': 'postgres://postgres@routefinder-db:5432/routefinder',
            'POSTGRES_PASSWORD': 'secret_password_123',
        }
        with patch.dict('os.environ', env_vars, clear=True):
            config = get_database_config(env_mock, '/tmp')
            self.assertEqual(config['ENGINE'], 'django.db.backends.postgresql')
            self.assertEqual(config['PASSWORD'], 'secret_password_123')
            self.assertEqual(config['HOST'], 'routefinder-db')
