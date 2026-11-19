from agents.debug.collector import collect_error
from agents.debug.analyzer import analyze_error
from agents.debug.fixer import generate_fix_suggestion


async def debug_error(error_content: str):

    error_info = collect_error(error_content)

    analysis = analyze_error(error_info)

    fix_suggestion = generate_fix_suggestion(error_info)

    return {
        "error_info": error_info,
        "analysis": analysis,
        "fix_suggestion": fix_suggestion,
    }
