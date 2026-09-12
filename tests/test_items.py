# tests/test_items.py
def test_items_requires_login(client):
    response = client.get("/contracts/1/items")
    assert response.status_code in (302, 401, 404)