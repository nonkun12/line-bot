import difflib


def generate_diff(original_code, fixed_code, original_file="app.py"):
    diff = difflib.unified_diff(
        original_code.splitlines(),
        fixed_code.splitlines(),
        fromfile=original_file,
        tofile=original_file + ".fixed",
        lineterm=""
    )

    return "\n".join(diff)


if __name__ == "__main__":

    with open("app.py", encoding="utf-8") as f:
        original = f.read()

    with open("app.py.fixed", encoding="utf-8") as f:
        fixed = f.read()

    patch = generate_diff(original, fixed)

    with open("app.py.patch", "w", encoding="utf-8") as f:
        f.write(patch)

    print("diff generated:")
    print("app.py.patch")
