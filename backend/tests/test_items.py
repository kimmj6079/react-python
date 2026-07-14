def test_create_item(client):
    response = client.post("/api/v1/items", json={"name": "keyboard", "description": "mechanical"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "keyboard"
    assert body["description"] == "mechanical"
    assert "id" in body


def test_list_items(client):
    client.post("/api/v1/items", json={"name": "mouse"})
    response = client.get("/api/v1/items")
    assert response.status_code == 200
    names = [item["name"] for item in response.json()]
    assert "mouse" in names


def test_get_item_not_found(client):
    response = client.get("/api/v1/items/999")
    assert response.status_code == 404
