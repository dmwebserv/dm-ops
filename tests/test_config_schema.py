"""
Tests that clients.yaml parses correctly and matches the schema every script
in scripts/ relies on: business-wide settings under `business:`, per-client
data under `clients:` (see CLAUDE.md / KNOWLEDGE.md "Config pattern").

Fully offline - only reads and parses the YAML file already in the repo.
"""

import os
import unittest

import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLIENTS_YAML_PATH = os.path.join(REPO_ROOT, "clients.yaml")

REQUIRED_BUSINESS_KEYS = {
    "sender_name": str,
    "from_email": str,
    "test_mode": bool,
    "test_email": str,
    "force_send_for_testing": bool,
    "care_plan_monthly_value": (int, float),
    "anthropic_model": str,
    "competitors": list,
}

REQUIRED_CLIENT_KEYS = {
    "id": str,
    "name": str,
    "url": str,
    "care_plan": bool,
    "contact_name": str,
    "contact_email": str,
}


class TestClientsYamlSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CLIENTS_YAML_PATH, encoding="utf-8") as f:
            cls.config = yaml.safe_load(f)

    def test_file_parses_to_a_dict(self):
        self.assertIsInstance(self.config, dict)

    def test_top_level_keys_are_only_business_and_clients(self):
        self.assertIn("business", self.config)
        self.assertIn("clients", self.config)
        # Business-wide config must live under `business:`, client data under
        # `clients:` - nothing else belongs at the top level (CLAUDE.md rule).
        unexpected = set(self.config.keys()) - {"business", "clients"}
        self.assertEqual(unexpected, set(), f"Unexpected top-level keys: {unexpected}")

    def test_business_section_has_required_keys_with_correct_types(self):
        business = self.config["business"]
        self.assertIsInstance(business, dict)
        for key, expected_type in REQUIRED_BUSINESS_KEYS.items():
            self.assertIn(key, business, f"business.{key} is missing")
            self.assertIsInstance(business[key], expected_type, f"business.{key} has the wrong type")

    def test_competitors_are_configured_business_wide_not_per_client(self):
        # KNOWLEDGE.md lesson: a client's trade rivals aren't the business's
        # competitors - competitors belong under business:, never under a
        # per-client entry.
        for client in self.config["clients"]:
            self.assertNotIn("competitors", client, f"client {client.get('id')} has its own competitors list")

    def test_clients_section_is_a_non_empty_list_of_well_formed_entries(self):
        clients = self.config["clients"]
        self.assertIsInstance(clients, list)
        self.assertGreater(len(clients), 0)
        for client in clients:
            self.assertIsInstance(client, dict)
            for key, expected_type in REQUIRED_CLIENT_KEYS.items():
                self.assertIn(key, client, f"client {client.get('id')} missing '{key}'")
                self.assertIsInstance(client[key], expected_type, f"client {client.get('id')}.{key} has the wrong type")

    def test_client_ids_are_unique(self):
        ids = [c["id"] for c in self.config["clients"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate client id found in clients.yaml")

    def test_no_em_or_en_dashes_anywhere_in_config(self):
        # CLAUDE.md non-negotiable: standard hyphens only, everywhere.
        offenders = []

        def scan(value, path):
            if isinstance(value, str):
                if "—" in value or "–" in value:
                    offenders.append(path)
            elif isinstance(value, dict):
                for k, v in value.items():
                    scan(v, f"{path}.{k}")
            elif isinstance(value, list):
                for i, v in enumerate(value):
                    scan(v, f"{path}[{i}]")

        scan(self.config, "clients.yaml")
        self.assertEqual(offenders, [], f"em/en dash found at: {offenders}")


if __name__ == "__main__":
    unittest.main()
