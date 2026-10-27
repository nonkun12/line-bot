import pytest
from app import app

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_add_and_list_expense(client):
    # Add an expense
    response = client.post('/expenses', json={'description': 'Coffee', 'amount': 3.5})
    assert response.status_code == 201
    data = response.get_json()
    assert data['description'] == 'Coffee'
    assert data['amount'] == 3.5
    assert 'id' in data

    # List expenses
    response = client.get('/expenses')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(e['description'] == 'Coffee' for e in data)

def test_invalid_payload(client):
    response = client.post('/expenses', json={'desc': 'Tea'})
    assert response.status_code == 400
