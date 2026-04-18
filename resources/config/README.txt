将 *.example 复制到「项目根目录」下的 config/ 并重命名去掉 .example：

  <项目根>/config/allowed_cmd.json
  <项目根>/config/allowed_ps_cmdlets.json

allowed_cmd.json 格式：{ "allowed": [ "与执行时完全一致的命令行（规范化空白后匹配）", ... ] }

allowed_ps_cmdlets.json 格式：{ "allowed": [ "Cmdlet-Name", ... ] }；脚本中出现的 cmdlet 须在此列表或为 Get-*。
