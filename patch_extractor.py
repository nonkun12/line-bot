def extract_diff(text):

    start = text.find("--- app.py")

    if start == -1:
        return ""

    return text[start:]
