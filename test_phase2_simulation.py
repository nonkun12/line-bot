from code_analyzer import localize_fault, extract_context
from fix_generator import extract_python_code, generate_patch
from patch_validator import review_patch, calculate_patch_safety_score


def run_simulation():
    simulated_logs = """
Traceback (most recent call last):
  File "app.py", line 250, in generate_reply
    result = call_mcp_tool()
Exception: test error
"""

    print("=== 1. Localize Fault ===")
    fault_info = localize_fault(simulated_logs)
    print("fault_info:", fault_info)

    with open("app.py", "r", encoding="utf-8") as f:
        code = f.read()

    print("\n=== 2. Extract Context ===")
    context = extract_context(code, function_name=fault_info["function"], line_number=fault_info["line"])
    print("extracted lines count:", len(context.splitlines()))

    print("\n=== 3. Simulated LLM Fixed Code Output ===")
    llm_output = """原因分析: call_mcp_toolの呼び出しエラーです。

```python
def generate_reply():
    try:
        result = call_mcp_tool()
    except Exception as e:
        result = str(e)
    return result
```
"""

    extracted_code = extract_python_code(llm_output)
    print("extracted python code:\n" + extracted_code)

    print("\n=== 4. Generate Patch ===")
    patch = generate_patch(context, extracted_code, "app.py")
    print(patch)

    print("\n=== 5. Review Patch & Safety Score ===")
    validation = review_patch(patch, target_function=fault_info["function"])
    print("Validation Result:\n" + str(validation))

    safety = calculate_patch_safety_score(patch, target_function=fault_info["function"])
    print("\nPatch Safety Score Result:\n" + str(safety))


if __name__ == "__main__":
    run_simulation()
