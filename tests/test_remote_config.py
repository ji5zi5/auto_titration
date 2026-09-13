import json
import unittest
import urllib.request
import urllib.error
from tools.windows_live_collect import LiveStreamState, start_live_stream_server

class RemoteConfigTests(unittest.TestCase):
    def test_shared_config_is_explicit_and_does_not_move_pump(self):
        commands=[]
        handle=start_live_stream_server("127.0.0.1",0,LiveStreamState(),
                                       pump_command_sender=commands.append)
        url="http://127.0.0.1:%s/api/remote/config" % handle.server.server_address[1]
        try:
            def get():
                return json.load(urllib.request.urlopen(url,timeout=2))
            self.assertIsNone(get()["config"])
            body={"pump_rate_ml_per_s":0.99,"titration_type":"weak_acid_strong_base",
                  "sample_volume_ml":20,"auto_stop_enabled":True}
            request=urllib.request.Request(url,data=json.dumps(body).encode(),
                headers={"Content-Type":"application/json"},method="POST")
            self.assertTrue(json.load(urllib.request.urlopen(request,timeout=2))["ok"])
            self.assertEqual(get()["config"],body)
            bad=urllib.request.Request(url,data=b'{"pump_rate_ml_per_s":0}',
                headers={"Content-Type":"application/json"},method="POST")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(bad,timeout=2)
            self.assertEqual(caught.exception.code,400)
            self.assertEqual(get()["config"],body)
            clear=urllib.request.Request(url,data=b'{"clear":true}',
                headers={"Content-Type":"application/json"},method="POST")
            self.assertTrue(json.load(urllib.request.urlopen(clear,timeout=2))["ok"])
            self.assertIsNone(get()["config"])
            self.assertEqual(commands,[])
        finally:
            handle.close()
