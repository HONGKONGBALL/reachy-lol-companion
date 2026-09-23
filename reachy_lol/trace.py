"""Bounded game analysis summaries; raw media and owner transcripts excluded."""
def decision_summary(situation,identity=None):
    identity=identity or {}
    private=set(identity.get('aliases') or [])
    for value in (identity.get('name'),):
        if value: private.add(value)
    for friend in identity.get('friends',[]):
        for key in ('name','nickname'):
            if friend.get(key): private.add(friend[key])
    def brief(value):
        text=str(value or '')
        for name in sorted(private,key=len,reverse=True):
            text=text.replace(name,'[玩家]')
        return text[:180]
    def claims(key):
        return [{'summary':brief(c.get('text')),'evidence':list(c.get('evidence',[]))[:4]}
                for c in situation.get(key,[])[:3]]
    return {'source':'model_analysis_unverified','observations':claims('observations'),
            'inferences':claims('inferences'),'unknowns':[brief(x) for x in situation.get('unknowns',[])[:3]],
            'contribution':brief(situation.get('contribution')),'outcome':brief(situation.get('outcome')),
            'meaningful':bool(situation.get('meaningful')),'safe':bool(situation.get('safe')),
            'safe_context':situation.get('safe_context','unknown')}
def dialogue_error_code(exc):
    """Only fixed local classifications; never persist model payloads/transcripts."""
    from pydantic import ValidationError
    if isinstance(exc,ValidationError):
        return 'invalid_model_schema'
    return {
        '控制意图缺少当前主人原句依据':'control_quote_not_in_utterance',
        '本局身份自报缺少必要内容，或应使用现有名册':'invalid_identity_report',
        '身份自报包含主人原句中没有的信息':'identity_report_not_in_utterance',
        '对话回复引用了无效证据或动作':'invalid_reply_evidence_or_motion',
        '纠正确认不能继续引用已撤回的底稿':'correction_reuses_evidence',
        '对局信息已变化或断开，请刷新身份后重新确认':'identity_roster_stale',
        '请选择本局唯一的玩家身份':'identity_not_unique',
        '朋友必须是本局其他玩家，不能选择自己':'friend_is_owner_or_unknown',
        '组排朋友必须是已确认的同队玩家':'friend_not_teammate',
    }.get(str(exc),'unclassified')

