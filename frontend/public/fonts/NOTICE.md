# 字体来源说明

`NotoSansSC-subset.ttf` 是 [Noto Sans CJK SC](https://github.com/notofonts/noto-cjk)（Regular 字重）的子集，
仅保留基本拉丁字母、常用标点与 CJK 统一表意文字（U+4E00–U+9FFF），用于 PDF 导出时嵌入真实文字
（而非截图），使导出的 PDF 可选中、可搜索。

生成方式：`pyftsubset` 按 Unicode 范围抽取子集，再用 `otf2ttf`（fontTools + cu2qu）把 CFF 轮廓转换为
TrueType 轮廓——jsPDF 的字体嵌入只支持 TrueType（glyf），不支持 CJK 常见的 CFF/OpenType 字体。
实际导出时 jsPDF 还会按文档里用到的字符再次子集化，单个 PDF 文件不会携带整个字库。

按 [SIL Open Font License 1.1](./LICENSE.txt) 授权，允许修改、子集化与再分发。
