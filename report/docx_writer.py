"""Minimal .docx writer using only the standard library (zipfile + XML strings).

Why hand-written: python-docx / docx-js are not on the project's approved dependency list, and this
needs only a small subset of WordprocessingML: styles, paragraphs, runs, lists, tables, inline
images, fields (TOC, PAGE, SEQ, PAGEREF), bookmarks and a footer with page numbers.
Element order inside pPr / rPr / tblPr / tcPr / sectPr follows the OOXML schema, because Word
rejects some out-of-order files.
"""
from __future__ import annotations

import re
import struct
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "Times New Roman"
MONO = "Consolas"
PAGE_W, PAGE_H, MARGIN = 11906, 16838, 1440          # A4 in twips, 1 inch margins
CONTENT_W = PAGE_W - 2 * MARGIN                      # 9026 twips
EMU_PER_INCH = 914400
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def t(text: str) -> str:
    return f'<w:t xml:space="preserve">{escape(text)}</w:t>'


class Doc:
    def __init__(self, title: str, author: str):
        self.title, self.author = title, author
        self.body: list[str] = []
        self.media: list[tuple[str, Path]] = []      # (name in package, file)
        self._bm = 0
        self._img = 0
        self._numbered = 0                          # numbered-list instances created
        self.num_instances: list[int] = []

    # ------------------------------------------------------------------ runs
    @staticmethod
    def run(text: str, bold=False, italic=False, mono=False, size: int | None = None, color: str | None = None,
            underline=False) -> str:
        rpr = ""
        if mono:
            rpr += f'<w:rFonts w:ascii="{MONO}" w:hAnsi="{MONO}" w:cs="{MONO}"/>'
        if bold:
            rpr += "<w:b/><w:bCs/>"
        if italic:
            rpr += "<w:i/><w:iCs/>"
        if color:
            rpr += f'<w:color w:val="{color}"/>'
        if size:
            rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
        if underline:
            rpr += '<w:u w:val="single"/>'
        return f"<w:r>{f'<w:rPr>{rpr}</w:rPr>' if rpr else ''}{t(text)}</w:r>"

    @staticmethod
    def field(instr: str, cached: str, bold=False, size: int | None = None) -> str:
        rpr = ("<w:rPr>" + ("<w:b/><w:bCs/>" if bold else "") + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "") + "</w:rPr>")
        rpr = rpr if rpr != "<w:rPr></w:rPr>" else ""
        return (f'<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'
                f'<w:r>{rpr}<w:instrText xml:space="preserve"> {escape(instr)} </w:instrText></w:r>'
                f'<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>'
                f'<w:r>{rpr}{t(cached)}</w:r>'
                f'<w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r>')

    def bookmark(self, name: str, inner: str) -> str:
        self._bm += 1
        return f'<w:bookmarkStart w:id="{self._bm}" w:name="{name}"/>{inner}<w:bookmarkEnd w:id="{self._bm}"/>'

    def inline(self, text: str, size: int | None = None, base_bold=False) -> str:
        """**bold**, *italic* and `code` markers inside a paragraph of text."""
        out = []
        for tok in re.split(r"(\*\*.+?\*\*|`.+?`|(?<!\*)\*[^*\n]+?\*(?!\*))", text):
            if not tok:
                continue
            if tok.startswith("**") and tok.endswith("**"):
                out.append(self.run(tok[2:-2], bold=True, size=size))
            elif tok.startswith("`") and tok.endswith("`"):
                out.append(self.run(tok[1:-1], mono=True, size=(size - 2 if size else 21), bold=base_bold))
            elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
                out.append(self.run(tok[1:-1], italic=True, size=size, bold=base_bold))
            else:
                out.append(self.run(tok, size=size, bold=base_bold))
        return "".join(out)

    # ------------------------------------------------------------------ paragraphs
    @staticmethod
    def ppr(style=None, keep_next=False, keep_lines=False, page_break=False, numid=None, ilvl=0, border=None, shade=None,
            spacing=None, ind=None, jc=None) -> str:
        x = ""
        if style:
            x += f'<w:pStyle w:val="{style}"/>'
        if keep_next:
            x += "<w:keepNext/>"
        if keep_lines:
            x += "<w:keepLines/>"
        if page_break:
            x += "<w:pageBreakBefore/>"
        if numid is not None:
            x += f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{numid}"/></w:numPr>'
        if border:
            x += ("<w:pBdr>" + "".join(f'<w:{s} w:val="{border}" w:sz="8" w:space="8" w:color="808080"/>' for s in ("top", "left", "bottom", "right")) + "</w:pBdr>")
        if shade:
            x += f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>'
        if spacing:
            x += "<w:spacing " + " ".join(f'w:{k}="{v}"' for k, v in spacing.items()) + "/>"
        if ind:
            x += "<w:ind " + " ".join(f'w:{k}="{v}"' for k, v in ind.items()) + "/>"
        if jc:
            x += f'<w:jc w:val="{jc}"/>'
        return f"<w:pPr>{x}</w:pPr>" if x else ""

    def para(self, runs_xml: str, **kw) -> str:
        xml = f"<w:p>{self.ppr(**kw)}{runs_xml}</w:p>"
        self.body.append(xml)
        return xml

    def text(self, text: str, **kw) -> None:
        self.para(self.inline(text), **kw)

    def heading(self, level: int, text: str, bookmark: str | None = None) -> None:
        run = self.run(text)
        self.para(self.bookmark(bookmark, run) if bookmark else run, style=f"Heading{level}")

    def page_break(self) -> None:
        self.body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    def empty(self, n: int = 1) -> None:
        for _ in range(n):
            self.body.append("<w:p/>")

    # ------------------------------------------------------------------ lists
    def bullets(self, items: list[str]) -> None:
        for it in items:
            self.para(self.inline(it), style="ListParagraph", numid=1)

    def numbered(self, items: list[str]) -> None:
        self._numbered += 1
        numid = 10 + self._numbered
        self.num_instances.append(numid)
        for it in items:
            self.para(self.inline(it), style="ListParagraph", numid=numid)

    # ------------------------------------------------------------------ code and images
    def code(self, lines: list[str], size: int = 18) -> None:
        for i, line in enumerate(lines):
            line = line.replace("\t", "    ").rstrip("\n")
            self.para(self.run(line or " ", mono=True, size=size), style="Code",
                      keep_next=(i < len(lines) - 1 and len(lines) <= 40))

    def image(self, path: Path, width_in: float, keep_next=True) -> None:
        w_px, h_px = png_size(path)
        cx = int(width_in * EMU_PER_INCH)
        cy = int(cx * h_px / w_px)
        self._img += 1
        rid, name = f"rIdImg{self._img}", f"image{self._img}.png"
        self.media.append((name, path))
        drawing = (
            f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{self._img}" name="Picture {self._img}" descr="{escape(path.stem)}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            f'<pic:nvPicPr><pic:cNvPr id="{self._img}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>")
        self.para(f"<w:r>{drawing}</w:r>", keep_next=keep_next, jc="center", spacing={"before": 120, "after": 60, "line": 240, "lineRule": "auto"})

    # ------------------------------------------------------------------ tables
    def table(self, header: list[str], rows: list[list[str]], widths: list[float], size: int = 20, header_fill="D9D9D9",
              align: list[str] | None = None, repeat_header=True, bold_first_col=False) -> None:
        total = sum(widths)
        cw = [int(CONTENT_W * w / total) for w in widths]
        cw[-1] += CONTENT_W - sum(cw)
        align = align or ["left"] * len(header)

        def cell(text: str, w: int, fill=None, bold=False, jc="left") -> str:
            tcpr = f'<w:tcW w:w="{w}" w:type="dxa"/>' + (f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else "")
            paras = []
            for line in str(text).split("\n"):
                ref = re.match(r"\{\{PAGEREF:(\w+)\}\}$", line)
                content = self.field(f"PAGEREF {ref.group(1)} \\h", "-", size=size) if ref else self.run(line, size=size, bold=bold)
                paras.append(f'<w:p><w:pPr><w:pStyle w:val="TableText"/><w:jc w:val="{jc}"/></w:pPr>{content}</w:p>')
            return f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{''.join(paras)}</w:tc>"

        borders = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="000000"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
        xml = (f'<w:tbl><w:tblPr><w:tblW w:w="{CONTENT_W}" w:type="dxa"/><w:jc w:val="center"/><w:tblBorders>{borders}</w:tblBorders>'
               '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="90" w:type="dxa"/>'
               '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr>'
               "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in cw) + "</w:tblGrid>")
        hdr = "".join(cell(h, w, fill=header_fill, bold=True, jc="center") for h, w in zip(header, cw))
        xml += f'<w:tr><w:trPr><w:cantSplit/>{"<w:tblHeader/>" if repeat_header else ""}</w:trPr>{hdr}</w:tr>'
        for r in rows:
            cells = "".join(cell(c, w, bold=(bold_first_col and i == 0), jc=align[i]) for i, (c, w) in enumerate(zip(r, cw)))
            xml += f"<w:tr><w:trPr><w:cantSplit/></w:trPr>{cells}</w:tr>"
        xml += "</w:tbl>"
        self.body.append(xml)
        self.body.append('<w:p><w:pPr><w:spacing w:before="0" w:after="120" w:line="240" w:lineRule="auto"/></w:pPr></w:p>')

    def raw_table(self, rows_xml: str) -> None:
        self.body.append(rows_xml)

    # ------------------------------------------------------------------ package parts
    def _styles(self) -> str:
        def style(sid, name, based="Normal", nxt=None, ppr="", rpr="", ui=None, qf=True):
            return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>'
                    + (f'<w:basedOn w:val="{based}"/>' if based else "") + (f'<w:next w:val="{nxt}"/>' if nxt else "")
                    + (f'<w:uiPriority w:val="{ui}"/>' if ui else "") + ("<w:qFormat/>" if qf else "")
                    + (f"<w:pPr>{ppr}</w:pPr>" if ppr else "") + (f"<w:rPr>{rpr}</w:rPr>" if rpr else "") + "</w:style>")

        fonts = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}" w:eastAsia="{FONT}"/>'
        head = lambda sz: f'{fonts}<w:b/><w:bCs/><w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>'
        return (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {NS}>'
            f'<w:docDefaults><w:rPrDefault><w:rPr>{fonts}<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-IN"/></w:rPr></w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
            '<w:pPr><w:spacing w:after="120" w:line="360" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr></w:style>'
            + style("Heading1", "heading 1", nxt="Normal", ppr='<w:keepNext/><w:keepLines/><w:pageBreakBefore/><w:spacing w:before="0" w:after="240" w:line="360" w:lineRule="auto"/><w:jc w:val="left"/><w:outlineLvl w:val="0"/>', rpr=head(32), ui=9)
            + style("Heading2", "heading 2", nxt="Normal", ppr='<w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="120" w:line="360" w:lineRule="auto"/><w:jc w:val="left"/><w:outlineLvl w:val="1"/>', rpr=head(28), ui=9)
            + style("Heading3", "heading 3", nxt="Normal", ppr='<w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="100" w:line="360" w:lineRule="auto"/><w:jc w:val="left"/><w:outlineLvl w:val="2"/>', rpr=head(24), ui=9)
            + style("FrontHeading", "Front Heading", nxt="Normal", ppr='<w:keepNext/><w:pageBreakBefore/><w:spacing w:before="0" w:after="240" w:line="360" w:lineRule="auto"/><w:jc w:val="center"/>', rpr=head(32))
            + style("Caption", "caption", nxt="Normal", ppr='<w:keepLines/><w:spacing w:before="60" w:after="200" w:line="276" w:lineRule="auto"/><w:jc w:val="center"/>', rpr=f'{fonts}<w:b/><w:bCs/><w:sz w:val="22"/><w:szCs w:val="22"/>')
            + style("TableCaption", "Table Caption", based="Caption", nxt="Normal", ppr='<w:keepNext/><w:spacing w:before="200" w:after="80" w:line="276" w:lineRule="auto"/><w:jc w:val="center"/>')
            + style("TableText", "Table Text", ppr='<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="left"/>', rpr='<w:sz w:val="20"/><w:szCs w:val="20"/>')
            + style("Code", "Code", ppr='<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="120" w:right="120"/><w:jc w:val="left"/>', rpr=f'<w:rFonts w:ascii="{MONO}" w:hAnsi="{MONO}" w:cs="{MONO}"/><w:sz w:val="18"/><w:szCs w:val="18"/>')
            + style("ListParagraph", "List Paragraph", ppr='<w:spacing w:after="60" w:line="360" w:lineRule="auto"/><w:contextualSpacing/><w:jc w:val="both"/>')
            + style("CoverTitle", "Cover Title", ppr='<w:spacing w:before="120" w:after="120" w:line="276" w:lineRule="auto"/><w:jc w:val="center"/>', rpr=f'{fonts}<w:b/><w:bCs/><w:sz w:val="28"/><w:szCs w:val="28"/>')
            + style("TOC1", "toc 1", nxt="Normal", ppr=f'<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="{CONTENT_W}"/></w:tabs><w:spacing w:before="120" w:after="40" w:line="276" w:lineRule="auto"/><w:jc w:val="left"/>', rpr="<w:b/><w:bCs/>", ui=39, qf=False)
            + style("TOC2", "toc 2", nxt="Normal", ppr=f'<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="{CONTENT_W}"/></w:tabs><w:spacing w:after="20" w:line="276" w:lineRule="auto"/><w:ind w:left="240"/><w:jc w:val="left"/>', ui=39, qf=False)
            + style("TOC3", "toc 3", nxt="Normal", ppr=f'<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="{CONTENT_W}"/></w:tabs><w:spacing w:after="20" w:line="276" w:lineRule="auto"/><w:ind w:left="480"/><w:jc w:val="left"/>', ui=39, qf=False)
            + '<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr></w:style>'
            + "</w:styles>")

    def _numbering(self) -> str:
        bullet = ('<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>'
                  '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/>'
                  '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/></w:rPr></w:lvl></w:abstractNum>')
        number = ('<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>'
                  '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/>'
                  '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>')
        nums = '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
        for nid in self.num_instances:   # each numbered list restarts at 1
            nums += f'<w:num w:numId="{nid}"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering {NS}>{bullet}{number}{nums}</w:numbering>'

    def save(self, path: Path) -> None:
        sect = (f'<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter1"/><w:footerReference w:type="first" r:id="rIdFooter2"/>'
                f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/><w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" '
                'w:header="709" w:footer="709" w:gutter="0"/><w:titlePg/></w:sectPr>')
        document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{"".join(self.body)}{sect}</w:body></w:document>'
        footer1 = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
                   + self.field("PAGE", "1") + "</w:p></w:ftr>")
        footer2 = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr></w:p></w:ftr>'
        settings = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings {NS}><w:defaultTabStop w:val="720"/>'
                    '<w:updateFields w:val="true"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')
        ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
                  '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                  '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                  '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
                  '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
                  '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                  '<Override PartName="/word/footer2.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                  '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                  '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>')
        doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                    '<Relationship Id="rIdNum" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
                    '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
                    '<Relationship Id="rIdFooter1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
                    '<Relationship Id="rIdFooter2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer2.xml"/>'
                    + "".join(f'<Relationship Id="rIdImg{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{name}"/>'
                              for i, (name, _) in enumerate(self.media, 1)) + "</Relationships>")
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f"<dc:title>{escape(self.title)}</dc:title><dc:creator>{escape(self.author)}</dc:creator></cp:coreProperties>")
        app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
               "<Application>Microsoft Office Word</Application></Properties>")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ctypes)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", document)
            z.writestr("word/_rels/document.xml.rels", doc_rels)
            z.writestr("word/styles.xml", self._styles())
            z.writestr("word/numbering.xml", self._numbering())
            z.writestr("word/settings.xml", settings)
            z.writestr("word/footer1.xml", footer1)
            z.writestr("word/footer2.xml", footer2)
            z.writestr("docProps/core.xml", core)
            z.writestr("docProps/app.xml", app)
            for name, file in self.media:
                z.write(file, f"word/media/{name}")
