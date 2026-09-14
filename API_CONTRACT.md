# API接口契约

## POST /runs

创建实验。

输入：

``` json
{
"concept":"",
"pain_point":"",
"alternative":""
}
```

## GET /runs/{id}

查询实验状态。

## POST /runs/{id}/challenge

执行单变量挑战。

## GET /runs/{id}/report

下载Markdown报告。

## GET /health

健康检查。

## v20 综合诊断和恢复
- `POST /runs/{id}/diagnosis`：对已完成实验生成/重试综合诊断，202；运行中返回409。旧记录也支持。
- `POST /runs/{id}/retry`：恢复失败实验，保留完成的角色，202；非失败返回409。
- `GET /runs/{id}` 新增 profiles_json、diagnosis_json、diagnosis_error。综合诊断失败时五角色结果仍可查看，报告页面显示重试。
- 综合报告字段：executive_summary、core_barriers、unexpected_values、value_gap_note、direction、rationale、pivot_conditions、next_steps、limitations。
- 挑战复制 raw_text、structured_json、profiles_json 以及三个核心字段；原实验不被修改。
- 所有上述接口需要登录并验证记录归属。

## GET /runs/{id}/report.docx
已完成实验的Word报告，返回application/vnd.openxmlformats-officedocument.wordprocessingml.document及附件文件名。认证和归属检查与Markdown一致；未完成返回409。生成使用Python标准库，不需要服务器安装Word或LibreOffice，不触发LLM调用。Word仅用于本轮文档排版验收。
