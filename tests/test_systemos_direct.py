from cous.cli.commands import build_router
from cous.clients.opentracy import OpenTracyClient
from cous.config import OpenTracyConfig


def test_direct_client_sends_only_order_and_uses_model_timeout():
    calls=[]
    class Http:
        def post(self,url,payload,*,timeout=None):
            calls.append((url,payload,timeout));return {"source":"systemos_live"}
    client=object.__new__(OpenTracyClient)
    client._diagnosis_auth=Http();client._runtime_url="http://127.0.0.1:8001"
    client._config=OpenTracyConfig(chat_timeout=900)
    assert client.diagnose_systemos("1141")["source"]=="systemos_live"
    assert calls==[("http://127.0.0.1:8001/v3/systemos/diagnosis",{"order":"1141"},900)]


def test_os_command_does_not_upload_or_diagnose_local_capture(make_context):
    ctx=make_context();orders=[];texts=[]
    class Live:
        def diagnose_systemos(self,order):
            orders.append(order)
            return {"order":order,"conclusion":"Consulta real","limitations":[],"snapshot_hash":"h","consulted_at":"now"}
    ctx.opentracy=Live();ctx.post_assistant=texts.append
    router=build_router()
    assert router.dispatch("/diagnostico os 1141",ctx) is True
    assert router.dispatch("/diagnostico 1134",ctx) is True
    assert orders==["1141","1134"]
    assert "Consulta real" in texts[0]

    assert ctx.session.last_user_message()=="/diagnostico os 1134"
    assert "Consulta real" in ctx.session.last_assistant_message()
