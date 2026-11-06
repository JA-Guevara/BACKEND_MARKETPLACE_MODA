def test_alta_cerrada_sin_variable(world,monkeypatch):
    monkeypatch.delenv('SIGNUP_ENABLED',raising=False)
    for method,path,body in [('post','/signup',{}),('post','/signup/verify',{}),('get','/signup/slug?name=nueva-tienda',None)]:
        kwargs={'json':body} if body is not None else {}
        response=getattr(world.client,method)('/api/v1/public'+path,**kwargs)
        assert response.status_code==404 and response.json()['error']['code']=='signup_disabled',response.text


def test_alta_abierta_explicita_conserva_consulta_slug(world,monkeypatch):
    monkeypatch.setenv('SIGNUP_ENABLED','true')
    response=world.client.get('/api/v1/public/signup/slug?name=tienda-prueba-nueva')
    assert response.status_code==200,response.text
