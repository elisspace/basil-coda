import tempfile
import pathlib
import unittest
from discovery import tune_key, reserve

class DiscoveryTests(unittest.TestCase):
    def test_versions_and_covers_are_same_tune(self):
        self.assertEqual(tune_key('The Swinging Shepherd Blues (Remastered 2000)'), tune_key('The Swinging Shepherd Blues [Live]'))
        self.assertEqual(tune_key('Blue World - 2020 Remaster'),tune_key('Blue World'))
    def test_history_survives_reopen_and_rejects_new_recording(self):
        with tempfile.TemporaryDirectory() as d:
            db=pathlib.Path(d)/'history.sqlite'
            reserve(db,'abcdefghijk','Blue World','Orchestra A')
            with self.assertRaises(ValueError): reserve(db,'lmnopqrstuv','Blue World (Live)','Orchestra B')
            with self.assertRaises(ValueError): reserve(db,'abcdefghijk','Different Label','Orchestra A')
            reserve(db,'z1234567890','New Discovery','Orchestra B')

if __name__=='__main__':unittest.main()
