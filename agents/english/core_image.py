"""Free, deterministic English word core-image explanations.

This module intentionally uses a small reviewed local lexicon. It makes no network
calls and does not guess etymologies for words outside the lexicon.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WordEntry:
    word: str
    pronunciation: str
    core_image: str
    parts: str
    related: tuple[str, ...]
    example: str
    note: str = ""


_ENTRIES: dict[str, WordEntry] = {
    "inspect": WordEntry(
        word="inspect",
        pronunciation="インスペクト",
        core_image="中をよく見る → 詳しく調べる・検査する",
        parts="in-（中へ）+ spect（見る：ラテン語 specere 系）",
        related=("spectator（観客）", "spectacle（壮観・見もの）", "respect（語源上は同系の「見る」から発達）"),
        example="The mechanic inspected the car.（整備士は車を詳しく点検した。）",
        note="語形成は歴史的に変化しているため、in- + spect は学習用の目安です。",
    ),
    "respect": WordEntry(
        word="respect",
        pronunciation="リスペクト",
        core_image="相手を振り返って見る → 尊重する・敬意を払う",
        parts="re-（後ろへ／再び）+ spect（見る：ラテン語 specere 系）",
        related=("inspect（詳しく調べる）", "spectator（観客）", "perspective（視点）"),
        example="I respect your opinion.（私はあなたの意見を尊重します。）",
        note="現代英語の意味は単純なパーツの足し算だけでは説明できません。",
    ),
    "transport": WordEntry(
        word="transport",
        pronunciation="トランスポート",
        core_image="向こう側へ運ぶ → 輸送する・運ぶ",
        parts="trans-（向こうへ／越えて）+ port（運ぶ：ラテン語 portare）",
        related=("portable（持ち運べる）", "import（中へ持ち込む／輸入する）", "export（外へ運び出す／輸出する）"),
        example="The company transports food by train.（その会社は列車で食品を輸送する。）",
    ),
    "portable": WordEntry(
        word="portable",
        pronunciation="ポータブル",
        core_image="持ち運べる → 携帯できる",
        parts="port（運ぶ：ラテン語 portare）+ -able（〜できる）",
        related=("transport（輸送する）", "import（輸入する）", "export（輸出する）"),
        example="This is a portable charger.（これは携帯用充電器です。）",
    ),
    "import": WordEntry(
        word="import",
        pronunciation="インポート",
        core_image="中へ運び込む → 輸入する",
        parts="im-（in- の変化形：中へ）+ port（運ぶ）",
        related=("export（輸出する）", "transport（輸送する）", "portable（持ち運べる）"),
        example="Japan imports coffee.（日本はコーヒーを輸入する。）",
    ),
    "export": WordEntry(
        word="export",
        pronunciation="エクスポート",
        core_image="外へ運び出す → 輸出する",
        parts="ex-（外へ）+ port（運ぶ）",
        related=("import（輸入する）", "transport（輸送する）", "portable（持ち運べる）"),
        example="They export cars to many countries.（彼らは多くの国へ車を輸出する。）",
    ),
    "spectator": WordEntry(
        word="spectator",
        pronunciation="スペクテイター",
        core_image="見る人 → 観客",
        parts="spect（見る）+ -ator（〜する人）",
        related=("inspect（詳しく調べる）", "respect（尊重する）", "spectacle（見もの）"),
        example="The spectators cheered loudly.（観客たちは大きな声援を送った。）",
    ),
    "perspective": WordEntry(
        word="perspective",
        pronunciation="パースペクティブ",
        core_image="物事を見る位置・角度 → 視点・見方",
        parts="per-（通して）+ spect（見る）に由来する語",
        related=("inspect（詳しく調べる）", "spectator（観客）", "respect（尊重する）"),
        example="Try to see it from her perspective.（彼女の視点からそれを見てみて。）",
        note="語源の細部は複雑なので、パーツは記憶の手がかりとして使ってください。",
    ),

    "circumstance": WordEntry(
        word="circumstance",
        pronunciation="サーカムスタンス",
        core_image="人や出来事の周りに立っている事情 → 状況・環境・境遇",
        parts="circum-（周囲に）+ stance（立つことに関係する語形）。ラテン語 circumstantia（周囲に立つこと・付随する事情）に由来。",
        related=("circum-（周囲に）", "circumnavigate（周航する）", "stand（立つ）"),
        example="Under the circumstances, we did our best.（そのような状況の中で、私たちは最善を尽くした。）",
        note="「周囲にある事情」というコアイメージは記憶の手がかりです。現代の意味を語のパーツだけで完全に説明するものではありません。",
    ),
    "environment": WordEntry(
        word="environment",
        pronunciation="エンヴァイロンメント",
        core_image="人や物を取り巻くもの・条件 → 環境",
        parts="environ（取り巻く、周囲）に関係する語形 + -ment（名詞を作る語尾）。フランス語系の語源を持つ語。",
        related=("environmental（環境の）", "surroundings（周囲のもの）", "environs（周辺地域）"),
        example="Children need a safe learning environment.（子どもには安全な学習環境が必要です。）",
        note="「取り巻くもの・条件」が中心イメージです。語源の細かな歴史を単純な分解だけで断定しないでください。",
    ),

    "postpone": WordEntry(
        word="postpone",
        pronunciation="ポストポーン",
        core_image="後ろの時点へ置く → 延期する・先送りする",
        parts="post-（後ろに／後で）+ pone（置く、ラテン語 ponere に由来する語根形）。",
        related=("position（位置・置くことに関連）", "component（構成要素）", "opponent（対戦相手）"),
        example="We postponed the meeting until Friday.（私たちは会議を金曜日まで延期した。）",
        note="「後ろの時点に置く」は意味を覚えるための手がかりです。関連語の歴史的な語形成はそれぞれ異なるため、形だけで同一の語源と断定しないでください。",
    ),

    "include": WordEntry(
        word="include",
        pronunciation="インクルード",
        core_image="内側に入れておく → 含める・含有する",
        parts="in-（中へ）+ clude（閉じる：ラテン語 claudere 系）",
        related=("exclude（除外する）", "conclude（結論づける）", "inclusion（包含）"),
        example="The price includes breakfast.（料金には朝食が含まれています。）",
        note="include と exclude を対比すると覚えやすい語です。",
    ),
    "exclude": WordEntry(
        word="exclude",
        pronunciation="エクスクルード",
        core_image="外へ閉め出す → 除外する・含めない",
        parts="ex-（外へ）+ clude（閉じる：ラテン語 claudere 系）",
        related=("include（含める）", "conclude（結論づける）", "exclusive（限定的な）"),
        example="The fee excludes tax.（その料金に税金は含まれていません。）",
        note="include と対比すると意味をつかみやすくなります。",
    ),
    "connect": WordEntry(
        word="connect",
        pronunciation="コネクト",
        core_image="結び合わせる → つなぐ・関連づける",
        parts="ラテン語 connectere（結び合わせる）に由来し、con-（一緒に）と nectere（結ぶ）に関連する形。",
        related=("connection（つながり）", "disconnect（切り離す）", "connector（接続器）"),
        example="This road connects the two towns.（この道路は2つの町をつないでいる。）",
        note="connect の con- は「一緒に」のイメージとして覚えられます。",
    ),
    "interrupt": WordEntry(
        word="interrupt",
        pronunciation="インタラプト",
        core_image="途中に割り込んで切る → さえぎる・中断する",
        parts="inter-（間に）+ rupt（破る：ラテン語 rumpere 系）",
        related=("disrupt（混乱させる）", "rupture（破裂）", "interruption（中断）"),
        example="Sorry to interrupt, but I have a question.（話をさえぎってすみませんが、質問があります。）",
        note="rupt を含む語には「破る・切る」のイメージが見られます。",
    ),
    "predict": WordEntry(
        word="predict",
        pronunciation="プリディクト",
        core_image="前もって言う → 予測する",
        parts="pre-（前もって）+ dict（言う：ラテン語 dicere 系）",
        related=("dictate（指示する）", "dictionary（辞書）", "contradict（反論する）"),
        example="Experts predict that prices will rise.（専門家は価格が上がると予測している。）",
        note="dict を含む語には「言う・述べる」に関係するものがあります。",
    ),
    "review": WordEntry(
        word="review",
        pronunciation="レビュー",
        core_image="もう一度見る → 見直す・評価する・批評する",
        parts="re-（再び）+ view（見る）",
        related=("preview（事前に見る）", "viewpoint（視点）", "revision（改訂）"),
        example="Please review the report before sending it.（送信前に報告書を見直してください。）",
        note="文脈により「評価する」「批評する」などの意味にもなります。",
    ),

    "visible": WordEntry(
        word="visible",
        pronunciation="ヴィジブル",
        core_image="目に入って見える → 目に見える・明らかな",
        parts="vis（見る：ラテン語 videre 系）+ -ible（〜できる）",
        related=("vision（視覚・展望）", "invisible（見えない）", "visual（視覚の）"),
        example="The stars were visible after sunset.（日没後、星が見えた。）",
        note="vis/vid は「見る」に関係する語根の手がかりです。",
    ),
    "dictate": WordEntry(
        word="dictate",
        pronunciation="ディクテイト",
        core_image="言葉で指示する → 指図する・書き取らせる",
        parts="dict（言う：ラテン語 dicere 系）に関係する語",
        related=("predict（予測する）", "contradict（反論する）", "dictation（書き取り）"),
        example="The rules dictate how the data is stored.（規則がデータの保存方法を定めている。）",
        note="dict を含む語には「言う・述べる」に関係するものがあります。",
    ),
    "contradict": WordEntry(
        word="contradict",
        pronunciation="コントラディクト",
        core_image="反対のことを言う → 否定する・矛盾する",
        parts="contra-（反対に）+ dict（言う：ラテン語 dicere 系）",
        related=("dictate（指示する）", "contradiction（矛盾）", "predict（予測する）"),
        example="The two reports contradict each other.（2つの報告書は互いに矛盾している。）",
        note="「反対に言う」は意味を覚えるための手がかりです。",
    ),
    "attract": WordEntry(
        word="attract",
        pronunciation="アトラクト",
        core_image="自分の方へ引き寄せる → 引きつける・魅了する",
        parts="ラテン語 attrahere（引き寄せる）に由来する語",
        related=("attraction（魅力・引力）", "distract（注意をそらす）", "attractive（魅力的な）"),
        example="Bright colors attract attention.（鮮やかな色は注意を引く。）",
        note="「引き寄せる」は物理的な引力にも、関心を引く意味にもつながります。",
    ),
    "distract": WordEntry(
        word="distract",
        pronunciation="ディストラクト",
        core_image="注意を別方向へ引っ張る → 気を散らす・注意をそらす",
        parts="dis-（離れて／別方向へ）+ tract（引く：ラテン語 trahere 系）",
        related=("attract（引きつける）", "distraction（気の散ること）", "tract（引くことに関係する語根）"),
        example="Noise can distract me while I work.（作業中、騒音で気が散ることがある。）",
        note="attract と並べて覚えると、引きつける／注意をそらすの対比になります。",
    ),
}


    "preview": WordEntry(
        word="preview",
        pronunciation="プレビュー",
        core_image="本番の前に見る → 予告編・事前確認",
        parts="pre-（前もって）+ view（見る）",
        related=("review（見直す）", "viewpoint（視点）", "previewer（事前確認する人・もの）"),
        example="We watched a preview of the film.（私たちは映画の予告編を見た。）",
        note="「前もって見る」は覚えるためのイメージです。",
    ),
    "prevent": WordEntry(
        word="prevent",
        pronunciation="プリベント",
        core_image="先回りして起こらないようにする → 防ぐ・予防する",
        parts="ラテン語 praevenire（先に来る）に由来する語。pre-（前に）と venire（来る）に関連。",
        related=("prevention（予防）", "preventable（防止できる）", "intervene（介入する）"),
        example="A seat belt can prevent serious injuries.（シートベルトは重傷を防ぐことがある。）",
        note="「先回りする」は意味をつかむための手がかりです。",
    ),
    "intervene": WordEntry(
        word="intervene",
        pronunciation="インタービーン",
        core_image="出来事の間に入る → 介入する・仲裁する",
        parts="inter-（間に）+ vene（来る：ラテン語 venire 系）に関係する語。",
        related=("prevent（防ぐ）", "intervention（介入）", "convenient（都合のよい）"),
        example="The teacher intervened in the argument.（先生は口論に介入した。）",
        note="語の歴史を現代のパーツだけで完全に説明するものではありません。",
    ),
    "invent": WordEntry(
        word="invent",
        pronunciation="インベント",
        core_image="新しいものを見つけ出す → 発明する・考案する",
        parts="ラテン語 invenire（見つける）に由来する語。",
        related=("invention（発明）", "inventor（発明家）", "inventory（在庫一覧：語源上の歴史は別途注意）"),
        example="She invented a simple tool.（彼女は簡単な道具を発明した。）",
        note="「新しいものを見つけ出す」は記憶の手がかりです。",
    ),
    "event": WordEntry(
        word="event",
        pronunciation="イベント",
        core_image="起こって現れること → 出来事・行事",
        parts="ラテン語 evenire（起こる・生じる）に由来する語。",
        related=("eventually（最終的に）", "eventful（出来事の多い）", "prevent（防ぐ）"),
        example="The event starts at six.（その行事は6時に始まる。）",
        note="関連語は綴りだけで同じ意味になるわけではありません。",
    ),
    "manufacture": WordEntry(
        word="manufacture",
        pronunciation="マニュファクチャー",
        core_image="手を使って作る → 製造する・製造",
        parts="ラテン語 manus（手）と facere（作る）に由来する語。",
        related=("manufacturer（製造業者）", "manufacturing（製造）", "manual（手作業の・手引書）"),
        example="The factory manufactures medical equipment.（その工場は医療機器を製造する。）",
        note="現在は機械による製造にも広く使います。",
    ),
    "manual": WordEntry(
        word="manual",
        pronunciation="マニュアル",
        core_image="手で行うもの／手元で使う案内 → 手動の・説明書",
        parts="ラテン語 manus（手）に由来する語。",
        related=("manufacture（製造する）", "manually（手動で）", "manuscript（手書き原稿）"),
        example="Please read the user manual.（取扱説明書を読んでください。）",
        note="manual は「手動の」と「説明書」の両方で使われます。",
    ),
    "construct": WordEntry(
        word="construct",
        pronunciation="コンストラクト",
        core_image="部材を組み立てる → 建設する・構成する",
        parts="con-（一緒に）+ struct（組み立てる：ラテン語 struere 系）",
        related=("structure（構造）", "instruct（指示する）", "destruction（破壊）"),
        example="They constructed a bridge over the river.（彼らは川に橋を架けた。）",
        note="語根のイメージは理解の手がかりで、現代の意味は文脈で判断します。",
    ),
    "destruct": WordEntry(
        word="destruct",
        pronunciation="ディストラクト",
        core_image="組み立てられたものを崩す → 破壊する",
        parts="de-（離す・下へなど）+ struct（組み立てる語根に関連）。destruct は主に複合語で見られます。",
        related=("destroy（破壊する）", "destruction（破壊）", "construct（建設する）"),
        example="The device has a self-destruct feature.（その装置には自爆機能がある。）",
        note="destruct 単独より self-destruct などの形が一般的です。",
    ),
    "instruct": WordEntry(
        word="instruct",
        pronunciation="インストラクト",
        core_image="順序立てて示す → 指示する・教える",
        parts="ラテン語 instruere（整える・準備する・教える）に由来し、struct 系の語形と関係します。",
        related=("instruction（指示・説明）", "instructor（指導者）", "construct（組み立てる）"),
        example="The guide instructed us to wait here.（ガイドはここで待つよう指示した。）",
        note="「組み立てて示す」は記憶のためのイメージです。",
    ),
    "structure": WordEntry(
        word="structure",
        pronunciation="ストラクチャー",
        core_image="部材を組み合わせた形 → 構造・仕組み",
        parts="ラテン語 structura（組み立て）に由来し、struere（組み立てる）と関係する語。",
        related=("construct（建設する）", "instruct（指示する）", "restructure（再構築する）"),
        example="The report has a clear structure.（その報告書は構成が明確だ。）",
        note="建物だけでなく、文章・組織・データの構造にも使います。",
    ),
    "inject": WordEntry(
        word="inject",
        pronunciation="インジェクト",
        core_image="中へ投げ入れる → 注入する",
        parts="in-（中へ）+ ject（投げる：ラテン語 jacere 系）",
        related=("injection（注入）", "reject（拒否する）", "project（投影する・計画する）"),
        example="The nurse injected the medicine carefully.（看護師は注意深く薬を注射した。）",
        note="「投げ入れる」は語源イメージで、実際の意味は文脈により変わります。",
    ),
    "reject": WordEntry(
        word="reject",
        pronunciation="リジェクト",
        core_image="押し返す → 拒否する・却下する",
        parts="re-（後ろへ・返して）+ ject（投げる：ラテン語 jacere 系）",
        related=("rejection（拒絶）", "inject（注入する）", "project（投影する）"),
        example="The editor rejected the proposal.（編集者は提案を却下した。）",
        note="「押し返す」は意味を思い出すための手がかりです。",
    ),
    "project": WordEntry(
        word="project",
        pronunciation="プロジェクト",
        core_image="前へ投げ出す → 投影する・見積もる・計画する",
        parts="pro-（前へ）+ ject（投げる：ラテン語 jacere 系）",
        related=("projection（投影・予測）", "reject（却下する）", "inject（注入する）"),
        example="The team projected costs for next year.（チームは来年の費用を見積もった。）",
        note="名詞 project は「計画・事業」、動詞 project は「投影する・予測する」などの意味です。",
    ),
    "describe": WordEntry(
        word="describe",
        pronunciation="ディスクライブ",
        core_image="特徴を書き表す → 描写する・説明する",
        parts="ラテン語 describere（書き写す・記述する）に由来する語。",
        related=("description（説明・描写）", "describe（描写する）", "prescribe（処方する・規定する）"),
        example="Can you describe what happened?（何が起きたか説明してくれますか。）",
        note="「書き表す」は意味を覚えるための手がかりです。",
    ),
    "prescribe": WordEntry(
        word="prescribe",
        pronunciation="プリスクライブ",
        core_image="前もって書いて指示する → 処方する・規定する",
        parts="pre-（前もって）+ scribe（書く：ラテン語 scribere 系）",
        related=("prescription（処方箋）", "describe（描写する）", "subscribe（購読する）"),
        example="The doctor prescribed a different medicine.（医師は別の薬を処方した。）",
        note="規則や手順を「規定する」という意味でも使います。",
    ),
    "subscribe": WordEntry(
        word="subscribe",
        pronunciation="サブスクライブ",
        core_image="名前を書き添えて参加を示す → 購読する・定期登録する",
        parts="sub-（下に）+ scribe（書く：ラテン語 scribere 系）に由来する語。",
        related=("subscription（定期購読・契約）", "subscriber（購読者）", "prescribe（処方する）"),
        example="I subscribe to a science magazine.（私は科学雑誌を定期購読している。）",
        note="語源の「署名する」から、現在はサービスの定期登録にも使われます。",
    ),
    "transcribe": WordEntry(
        word="transcribe",
        pronunciation="トランスクライブ",
        core_image="別の形へ書き写す → 書き起こす・転記する",
        parts="trans-（越えて／別の形へ）+ scribe（書く：ラテン語 scribere 系）",
        related=("transcription（書き起こし）", "describe（描写する）", "prescribe（規定する）"),
        example="Please transcribe the interview.（インタビューを書き起こしてください。）",
        note="音声を文字にする場合にも、文書を転記する場合にも使います。",
    ),
    "audience": WordEntry(
        word="audience",
        pronunciation="オーディエンス",
        core_image="耳を傾けて聞く人たち → 聴衆・観客",
        parts="ラテン語 audire（聞く）に由来する語。",
        related=("audio（音声）", "audible（聞こえる）", "audition（オーディション・聴力検査）"),
        example="The audience applauded at the end.（最後に観客は拍手した。）",
        note="舞台の観客だけでなく、配信や広告の対象者にも使います。",
    ),
    "audible": WordEntry(
        word="audible",
        pronunciation="オーディブル",
        core_image="耳で聞き取れる → 聞こえる・聞き取れる",
        parts="aud（聞く：ラテン語 audire 系）+ -ible（〜できる）",
        related=("audio（音声）", "audience（聴衆）", "inaudible（聞こえない）"),
        example="Her voice was barely audible.（彼女の声はかろうじて聞こえた。）",
        note="inaudible は in-（否定）を伴う対義語です。",
    ),
    "interact": WordEntry(
        word="interact",
        pronunciation="インターアクト",
        core_image="互いに働きかける → 相互作用する・交流する",
        parts="inter-（相互に・間で）+ act（行動する）",
        related=("interaction（相互作用）", "interactive（双方向の）", "react（反応する）"),
        example="Students interact in small groups.（生徒たちは小グループで交流する。）",
        note="人同士だけでなく、システムや物質の相互作用にも使います。",
    ),
    "emerge": WordEntry(
        word="emerge",
        pronunciation="イマージ",
        core_image="中から外へ現れる → 現れる・明らかになる",
        parts="ラテン語 emergere（浮かび上がる・現れる）に由来する語。",
        related=("emergency（緊急事態）", "emergence（出現）", "immerse（沈める）"),
        example="New details emerged during the meeting.（会議中に新たな詳細が明らかになった。）",
        note="物理的に現れる場合にも、情報が明らかになる場合にも使います。",
    ),
    "immerse": WordEntry(
        word="immerse",
        pronunciation="イマース",
        core_image="液体や活動の中に深く入れる → 浸す・没頭させる",
        parts="im-（中へ）+ merge（沈める：ラテン語 mergere 系）に由来する語。",
        related=("immersion（浸すこと・没入）", "submerge（沈める）", "emerge（現れる）"),
        example="She immersed herself in the book.（彼女は本に没頭した。）",
        note="水に浸す意味から、活動に深く没頭する意味にも広がります。",
    ),
    "submerge": WordEntry(
        word="submerge",
        pronunciation="サブマージ",
        core_image="水面の下へ沈める → 水没させる・沈む",
        parts="sub-（下へ）+ merge（沈める：ラテン語 mergere 系）",
        related=("submersion（水没）", "immerse（浸す）", "emerge（現れる）"),
        example="The road was submerged after the storm.（嵐の後、道路は水没した。）",
        note="比喩的に、仕事などに埋没する意味でも使われます。",
    ),
    "progress": WordEntry(
        word="progress",
        pronunciation="プログレス",
        core_image="前へ一歩ずつ進む → 進歩・進行する",
        parts="pro-（前へ）+ gress（歩み：ラテン語 gradi 系）に関係する語。",
        related=("progressive（進歩的な）", "regress（後退する）", "digress（話がそれる）"),
        example="We made good progress on the project.（私たちは計画を順調に進めた。）",
        note="名詞では「進歩・進捗」、動詞では「進む・進展する」です。",
    ),
    "regress": WordEntry(
        word="regress",
        pronunciation="リグレス",
        core_image="後ろへ戻る → 後退する・退行する",
        parts="re-（後ろへ／戻って）+ gress（歩み：ラテン語 gradi 系）に関係する語。",
        related=("regression（後退・回帰）", "progress（進歩）", "digress（話がそれる）"),
        example="The symptoms began to regress.（症状は後退し始めた。）",
        note="統計の regression は「回帰」という専門的な意味もあります。",
    ),
    "digress": WordEntry(
        word="digress",
        pronunciation="ダイグレス",
        core_image="本筋から横へ歩み出る → 話がそれる",
        parts="di-（別方向へ）+ gress（歩み：ラテン語 gradi 系）に関係する語。",
        related=("digression（脱線）", "progress（進歩）", "regress（後退する）"),
        example="Let me digress for a moment.（少し話を脱線させてください。）",
        note="主に話や文章が本題からそれることを表します。",
    ),
    "transfer": WordEntry(
        word="transfer",
        pronunciation="トランスファー",
        core_image="向こう側へ運び移す → 移す・転送する・転勤する",
        parts="trans-（越えて／向こうへ）+ fer（運ぶ：ラテン語 ferre 系）",
        related=("transport（輸送する）", "refer（言及する・参照する）", "transferable（移転可能な）"),
        example="Please transfer the file to this folder.（ファイルをこのフォルダーに移してください。）",
        note="データ・お金・人の移動など幅広く使います。",
    ),
    "refer": WordEntry(
        word="refer",
        pronunciation="リファー",
        core_image="話題や情報を別のものへ向ける → 言及する・参照する",
        parts="re-（戻して／再び）+ fer（運ぶ：ラテン語 ferre 系）に由来する語。",
        related=("reference（参照・推薦状）", "referral（紹介）", "transfer（移す）"),
        example="Please refer to page ten.（10ページを参照してください。）",
        note="refer to は「〜を参照する／〜に言及する」、refer someone to は「人を紹介する」です。",
    ),
    "prefer": WordEntry(
        word="prefer",
        pronunciation="プリファー",
        core_image="他より前に選ぶ → 〜をより好む",
        parts="pre-（前に）+ fer（運ぶ：ラテン語 ferre 系）に由来する語。",
        related=("preference（好み）", "preferable（より望ましい）", "refer（参照する）"),
        example="I prefer tea to coffee.（私はコーヒーより紅茶が好きです。）",
        note="prefer A to B は「BよりAを好む」という形です。",
    ),
    "offer": WordEntry(
        word="offer",
        pronunciation="オファー",
        core_image="相手の前に差し出す → 提供する・申し出る",
        parts="ラテン語 offerre（差し出す・提供する）に由来する語。",
        related=("offering（提供物・供物）", "offer to help（助けると申し出る）", "offering price（提示価格）"),
        example="She offered to help us.（彼女は私たちを手伝うと申し出た。）",
        note="物の提供にも、提案や申し出にも使います。",
    ),


_COMMAND_RE = re.compile(
    r"^(?:コアイメージ|語根|語幹|core\s*image|word\s*root)\s*[:：]?\s+([A-Za-z][A-Za-z'-]{0,63})\s*[?？。！!]*$",
    re.IGNORECASE,
)


def extract_core_image_word(message: str) -> str | None:
    """Return a word only for explicit core-image commands."""
    match = _COMMAND_RE.fullmatch(str(message or "").strip())
    return match.group(1).lower() if match else None


def explain_core_image(word: str) -> str:
    """Explain a reviewed word, or explicitly decline to guess."""
    normalized = str(word or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z'-]{0,63}", normalized):
        return "英単語を1語指定してください。例：コアイメージ inspect"

    entry = _ENTRIES.get(normalized)
    if entry is None:
        return (
            f"「{normalized}」は、現在の無料ローカル辞書に確かな解説がありません。\n"
            "語源や語根を推測で断定しないため、今回は説明を保留します。\n"
            "別の単語を試すか、辞書項目の追加を依頼してください。"
        )

    lines = [
        f"🔎 {entry.word}（{entry.pronunciation}）",
        f"コアイメージ：{entry.core_image}",
        f"語のパーツ：{entry.parts}",
        "関連語： " + " / ".join(entry.related),
        f"例文：{entry.example}",
    ]
    if entry.note:
        lines.append(f"補足：{entry.note}")
    lines.append("※無料のローカル解説です。外部APIへの問い合わせは行いません。")
    return "\n".join(lines)


def handle_core_image_command(message: str) -> str | None:
    """Return a response for an explicit command, or None if not a match."""
    word = extract_core_image_word(message)
    return explain_core_image(word) if word else None
