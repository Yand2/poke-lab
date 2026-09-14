"""Dependency-free editable Word report export using standard OOXML."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element, SubElement, tostring
import re

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
XML='http://www.w3.org/XML/1998/namespace'
def node(parent,tag,attrs=None):
    return SubElement(parent,'{'+W+'}'+tag,{'{'+W+'}'+k:str(v) for k,v in (attrs or {}).items()})
def text_run(p,text,bold=False,color=None):
    r=node(p,'r');pr=node(r,'rPr')
    if bold:node(pr,'b')
    if color:node(pr,'color',{'val':color})
    # Control characters forbidden in XML are omitted, ordinary unicode preserved.
    text=''.join(c for c in str(text) if ord(c)>=32 or c in '\n\t')
    for i,line in enumerate(text.split('\n')):
        if i:node(r,'br')
        t=node(r,'t');t.set('{'+XML+'}space','preserve');t.text=line
    return r

def paragraph(parent,text='',style=None):
    p=node(parent,'p');pr=node(p,'pPr')
    if style:node(pr,'pStyle',{'val':style})
    # Word can wrap Latin identifiers without forcing the page wider.
    node(pr,'wordWrap',{'val':'1'})
    pieces=re.split(r'(\*\*.*?\*\*)',text)
    for part in pieces:
        if part:text_run(p,part[2:-2] if part.startswith('**') and part.endswith('**') else part,part.startswith('**'))
    return p

def xml(e):return tostring(e,encoding='utf-8',xml_declaration=True)

def styles():
    root=Element('{'+W+'}styles')
    defaults=node(root,'docDefaults');rp=node(node(defaults,'rPrDefault'),'rPr')
    node(rp,'rFonts',{'ascii':'Calibri','hAnsi':'Calibri','eastAsia':'Microsoft YaHei'})
    node(rp,'sz',{'val':22});node(rp,'color',{'val':'273247'})
    pp=node(node(defaults,'pPrDefault'),'pPr');node(pp,'spacing',{'after':140,'line':330,'lineRule':'auto'});node(pp,'widowControl')
    specs=[('Normal','正文',22,'273247',False),('Title','报告标题',40,'000000',True),('Subtitle','副标题',24,'64748B',False),('Heading1','标题 1',29,'5145CD',True),('Heading2','标题 2',24,'273247',True),('Heading3','标题 3',22,'273247',True),('Caption','说明',18,'64748B',False),('Quote','提示',21,'5145CD',False)]
    for sid,name,size,color,bold in specs:
        st=node(root,'style',{'type':'paragraph','styleId':sid});node(st,'name',{'val':name})
        if sid!='Normal':node(st,'basedOn',{'val':'Normal'})
        pp=node(st,'pPr');rp=node(st,'rPr');node(rp,'sz',{'val':size});node(rp,'color',{'val':color})
        if bold:node(rp,'b')
        if sid.startswith('Heading') or sid in ['Title','Subtitle']:
            node(pp,'keepNext');node(pp,'keepLines');node(pp,'spacing',{'before':240,'after':140})
            if sid.startswith('Heading'):node(pp,'outlineLvl',{'val':int(sid[-1])-1})
        if sid=='Quote':
            node(pp,'shd',{'fill':'F0EEFC','val':'clear'});node(pp,'ind',{'left':180,'right':180});node(pp,'spacing',{'before':160,'after':200})
    return xml(root)

def export_docx(markdown):
    root=Element('{'+W+'}document');body=node(root,'body')
    header=Element('{'+W+'}hdr');paragraph(header,'POKE   /   创新概念研究','Caption')
    footer=Element('{'+W+'}ftr');p=paragraph(footer,'AI 模拟分析  ·  结论需真人验证     |     ','Caption');field=node(p,'fldSimple',{'instr':'PAGE'});text_run(field,'1')
    paragraph(body,'创新概念可行性与转型诊断报告','Title')
    paragraph(body,'五种视角  理解阻力与下一步验证方向','Subtitle')
    blocks=markdown.split('\n\n')
    metadata=[x for x in blocks if x.startswith(('实验编号：','创建时间：','模式：'))]
    if metadata:
        table=node(body,'tbl');props=node(table,'tblPr');node(props,'tblW',{'w':9360,'type':'dxa'});node(props,'tblLayout',{'type':'fixed'})
        borders=node(props,'tblBorders')
        for side in ['top','left','bottom','right','insideH','insideV']:node(borders,side,{'val':'single','sz':4,'color':'D9D9D9'})
        margins=node(props,'tblCellMar')
        for side in ['top','left','bottom','right']:node(margins,side,{'w':100,'type':'dxa'})
        grid=node(table,'tblGrid');node(grid,'gridCol',{'w':1700});node(grid,'gridCol',{'w':7660})
        for line in metadata:
            label,value=line.split('：',1);tr=node(table,'tr');node(node(tr,'trPr'),'cantSplit')
            for idx,t in enumerate([label,value]):
                cell=node(tr,'tc');cp=node(cell,'tcPr');node(cp,'vAlign',{'val':'center'});node(cp,'tcW',{'w':1700 if idx==0 else 7660,'type':'dxa'});node(cp,'shd',{'fill':'EEEAFB' if idx==0 else 'F7F8FC','val':'clear'});paragraph(cell,t,'Caption')
    for block in blocks:
        block=block.strip()
        if not block or block.startswith('# ') or block in metadata:continue
        if block.startswith('### '):paragraph(body,re.sub(r'[·/（）()]',' ',block[4:]),'Heading2')
        elif block.startswith('## '):paragraph(body,re.sub(r'[·/（）()]',' ',block[3:]),'Heading1')
        elif block.startswith('> '):paragraph(body,block[2:],'Quote')
        else:
            for line in block.split('\n'):
                if not line:continue
                m=re.match(r'^\d+\.\s+(.*)',line)
                if m:
                    p=paragraph(body,m[1]);np=node(p.find('{'+W+'}pPr'),'numPr');node(np,'ilvl',{'val':0});node(np,'numId',{'val':1})
                else:
                    # Short field labels become bold; the original content is unchanged.
                    if '：' in line and len(line.split('：',1)[0])<=12:
                        label,value=line.split('：',1);line='**'+label+'：**'+value
                    paragraph(body,line,'Caption' if line.startswith(('角色依据：','输入证据：')) else None)
    sect=node(body,'sectPr')
    for kind,rid in [('headerReference','rId2'),('footerReference','rId3')]:
        ref=node(sect,kind,{'type':'default'});ref.set('{'+R+'}id',rid)
    node(sect,'pgSz',{'w':12240,'h':15840})
    node(sect,'pgMar',{'top':1200,'right':1440,'bottom':1200,'left':1440,'header':600,'footer':600,'gutter':0})
    numbering=Element('{'+W+'}numbering');a=node(numbering,'abstractNum',{'abstractNumId':0});lvl=node(a,'lvl',{'ilvl':0});node(lvl,'start',{'val':1});node(lvl,'numFmt',{'val':'decimal'});node(lvl,'lvlText',{'val':'%1.'});pp=node(lvl,'pPr');node(pp,'ind',{'left':420,'hanging':360});num=node(numbering,'num',{'numId':1});node(num,'abstractNumId',{'val':0})
    ns='http://schemas.openxmlformats.org/package/2006/relationships'
    rel=Element('Relationships',xmlns=ns)
    for rid,type_,target in [('rId1','styles','styles.xml'),('rId2','header','header1.xml'),('rId3','footer','footer1.xml'),('rId4','numbering','numbering.xml')]:SubElement(rel,'Relationship',Id=rid,Type=R+'/'+type_,Target=target)
    top=Element('Relationships',xmlns=ns);SubElement(top,'Relationship',Id='rId1',Type=R+'/officeDocument',Target='word/document.xml')
    ct=Element('Types',xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    SubElement(ct,'Default',Extension='rels',ContentType='application/vnd.openxmlformats-package.relationships+xml');SubElement(ct,'Default',Extension='xml',ContentType='application/xml')
    for name,type_ in [('document','document.main'),('styles','styles'),('header1','header'),('footer1','footer'),('numbering','numbering')]:SubElement(ct,'Override',PartName='/word/'+name+'.xml',ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.'+type_+'+xml')
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for path,data in {'[Content_Types].xml':xml(ct),'_rels/.rels':xml(top),'word/document.xml':xml(root),'word/styles.xml':styles(),'word/header1.xml':xml(header),'word/footer1.xml':xml(footer),'word/numbering.xml':xml(numbering),'word/_rels/document.xml.rels':xml(rel)}.items():z.writestr(path,data)
    return out.getvalue()
