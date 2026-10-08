// 仅用于展示：不修改接口字段、存储值、原稿或剧本正文。
const Presentation = (() => {
  const fields = {
    text:'概括内容', original_story:'用户原稿', original:'用户原稿', draft:'当前剧本', story:'故事内容',
    constraints:'创作要求', outline:'故事骨架', card:'概括卡片', issues:'审核问题',
    related_facets:'关联卡片', evidence:'引用依据', quote:'引用原文', source:'内容来源',
    description:'问题说明', suggestion:'修改建议', needs_user:'需要用户补充',
    reviewed_version:'已审核版本', revision_count:'修订次数', version:'版本',
    interrupt_id:'确认记录', accepted_issue_ids:'已接受的问题', issue_id:'审核问题',
    direction_id:'故事方向', decisions:'处理方案', feedback:'补充说明',
    mode:'创作模式', status:'项目状态', max_calls:'调用上限', calls_used:'已用调用次数',
    theme:'主题与情绪', characters:'人物', plot:'剧情', props:'道具', scenes:'场景',
    actions:'动作与表演', camera:'镜头语言', visual_style:'视觉风格', sound:'声音', pacing:'节奏与规格',
    collaborative:'协作创作', faithful:'旧版忠于原稿', direct:'原稿直接制作', free:'自由编剧'
  };
  function text(value) {
    return String(value ?? '').replace(/\b[A-Za-z_][A-Za-z_0-9]*\b/g, key => fields[key] || key);
  }
  function label(map, key, fallback) { return map[key] || fallback; }
  function validation(detail) {
    if (typeof detail === 'string') return text(detail);
    if (!Array.isArray(detail)) return '输入格式有误，请检查填写内容。';
    return detail.map(error => {
      const location=(error.loc || []).filter(key => !['body','query','path'].includes(key))
        .map(key => typeof key === 'number' ? `第 ${key+1} 项` : (fields[key] || '输入项')).join(' · ');
      const messages={missing:'请填写此项。',string_too_long:'内容过长，请缩短后重试。',string_too_short:'内容过短，请补充。',literal_error:'请选择有效选项。',enum:'请选择有效选项。',int_parsing:'请输入整数。',json_invalid:'提交内容格式有误，请刷新后重试。'};
      return `${location || '输入内容'}：${messages[error.type] || '内容不符合要求，请检查后重试。'}`;
    }).join('；');
  }
  function preview(key,value) { return ['description','suggestion'].includes(key) ? text(value) : value; }
  function decision(item) {
    const name=label({adopt:'采用建议',replace:'替换建议',keep:'保留设定'},item.choice,'其他处理');
    return name+'：'+(item.choice==='adopt'?text(item.instruction):String(item.instruction ?? ''));
  }
  function error(value) {
    const raw=String(value ?? '');
    if(raw.includes('DEEPSEEK_API_KEY'))return '尚未配置模型服务密钥，请在本地配置中填写后重启应用。';
    if(/JSON|结构化|数据约定/.test(raw))return '模型返回的内容格式不符合要求，本次结果未采用。可在剩余额度内重试。';
    if(/Failed to fetch|NetworkError|Load failed/.test(raw))return '无法连接本地服务，请确认应用正在运行后重试。';
    if(/来源引用|不存在的原文/.test(raw))return 'AI 返回的引用无法在对应材料中核对，本次结果未通过校验。这不代表你必须修改原稿。';
    return text(raw);
  }
  return {text,label,validation,preview,decision,error};
})();
