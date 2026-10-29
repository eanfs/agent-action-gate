# SPDX-License-Identifier: Apache-2.0
import unittest

from agent_action_gate.yaml_lite import YamlError, loads


class YamlLiteTest(unittest.TestCase):
    def test_maps_lists_quotes_and_comments(self):
        document = loads(
            """
            # comment
            version: 1
            name: "has: colon"
            enabled: true
            items:
              - order_id
              - amount_cny
            rules:
              - id: refund.auto
                when:
                  amount_cny_lte: 100
                decision: allow
                reason: "金额 {amount_cny}"
            """
        )
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["name"], "has: colon")
        self.assertIs(document["enabled"], True)
        self.assertEqual(document["items"], ["order_id", "amount_cny"])
        self.assertEqual(document["rules"][0]["when"]["amount_cny_lte"], 100)
        self.assertEqual(document["rules"][0]["reason"], "金额 {amount_cny}")

    def test_tabs_floats_and_duplicate_keys_are_rejected(self):
        with self.assertRaises(YamlError):
            loads("version:\t1\n")
        with self.assertRaises(YamlError):
            loads("limit: 1.5\n")
        with self.assertRaises(YamlError):
            loads("a: 1\na: 2\n")
