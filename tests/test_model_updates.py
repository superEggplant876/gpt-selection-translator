from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_catalog import visible_models, choose_model
from translation_client import TranslationClient
from verify_connection import VerificationError


class Tests(unittest.TestCase):
    def test_unknown_future_identifiers_are_exposed_in_server_order(self):
        data = {'models':[{'slug':'future-model-2030', 'visibility':'list', 'display_name':'Future Model'},
                          {'slug':'old-model', 'visibility':'list'},
                          {'slug':'hidden-model', 'visibility':'hidden'},
                          {'slug':'future-model-2030', 'visibility':'list'}]}
        models = visible_models(data)
        self.assertEqual([m['slug'] for m in models], ['future-model-2030','old-model'])
        self.assertEqual(choose_model(models,'old-model',True),0)
        self.assertEqual(choose_model(models,'old-model',False),1)
        self.assertEqual(choose_model(models,'retired-model',False),0)

    def test_failure_keeps_the_last_good_catalog(self):
        client = TranslationClient('.')
        client.models = [{'slug':'last-good-model'}]
        with patch.object(client,'access',return_value='synthetic'), patch('translation_client.connection.get_json',return_value={'models':[]}):
            with self.assertRaises(VerificationError): client.load_models()
        self.assertEqual(client.models,[{'slug':'last-good-model'}])


if __name__ == '__main__': unittest.main(verbosity=2)

