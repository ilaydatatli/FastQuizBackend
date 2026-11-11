from django.test import override_settings
from rest_framework.test import APISimpleTestCase

ALLOWED_ORIGIN = "http://localhost:5173"


@override_settings(CORS_ALLOWED_ORIGINS=[ALLOWED_ORIGIN])
class HealthAndErrorFormatTests(APISimpleTestCase):
    def test_health_returns_ok(self):
        response = self.client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"status": "ok", "api_version": "v1"})

    def test_unknown_api_endpoint_returns_json_404(self):
        response = self.client.get("/api/v1/does-not-exist/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        body = response.json()
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertTrue(body["error"]["message"])

    def test_unknown_path_outside_api_returns_json_404(self):
        response = self.client.get("/nothing-here/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_wrong_method_uses_shared_error_format(self):
        response = self.client.post("/api/v1/health/", {}, format="json")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_cors_header_for_allowed_origin(self):
        response = self.client.get("/api/v1/health/", HTTP_ORIGIN=ALLOWED_ORIGIN)

        self.assertEqual(response["Access-Control-Allow-Origin"], ALLOWED_ORIGIN)
        self.assertNotIn("Access-Control-Allow-Credentials", response)

    def test_cors_preflight_allows_authorization_header(self):
        response = self.client.options(
            "/api/v1/health/",
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization, content-type",
        )

        self.assertEqual(response["Access-Control-Allow-Origin"], ALLOWED_ORIGIN)
        self.assertIn("authorization", response["Access-Control-Allow-Headers"])

    def test_no_cors_header_for_unknown_origin(self):
        response = self.client.get("/api/v1/health/", HTTP_ORIGIN="https://evil.example.com")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response)
