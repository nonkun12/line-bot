from flask import Flask, request, jsonify

app = Flask(__name__)

# In-memory storage for expenses
expenses = []

@app.route('/expenses', methods=['POST'])
def add_expense():
    """
    Add a new expense.
    Expected JSON payload: {"description": "...", "amount": ...}
    """
    data = request.get_json()
    if not data or 'description' not in data or 'amount' not in data:
        return jsonify({'error': 'Invalid payload'}), 400

    expense = {
        'id': len(expenses) + 1,
        'description': data['description'],
        'amount': data['amount']
    }
    expenses.append(expense)
    return jsonify(expense), 201

@app.route('/expenses', methods=['GET'])
def list_expenses():
    """
    Return the list of all expenses.
    """
    return jsonify(expenses), 200

if __name__ == '__main__':
    app.run(debug=True)
