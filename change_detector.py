def detect_change_needed(current_code, proposed_patch):

    result = []

    result.append(
        "🔍 Change Detector"
    )

    if not proposed_patch:
        result.append(
            "⚠️ 修正案がありません"
        )
        return "\n".join(result)


    # 代表的な無意味変更チェック

    if "to=user_id" in proposed_patch:

        if "to=user_id" in current_code:
            result.append(
                "⚠️ to=user_id は既に存在します"
            )
            result.append(
                "コード変更は不要の可能性があります"
            )
            return "\n".join(result)


    if proposed_patch.strip() == current_code.strip():

        result.append(
            "⚠️ 現在コードと修正案が同一です"
        )

    else:

        result.append(
            "✅ 変更が必要です"
        )


    return "\n".join(result)
