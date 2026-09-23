from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output'/'pdf'
OUT.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('YaHei',r'C:\Windows\Fonts\msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('YaHeiBold',r'C:\Windows\Fonts\msyhbd.ttc',subfontIndex=0))
pdfmetrics.registerFontFamily('YaHei',normal='YaHei',bold='YaHeiBold',italic='YaHei',boldItalic='YaHeiBold')
INK=colors.HexColor('#202A2C'); GREEN=colors.HexColor('#22594D'); PALE=colors.HexColor('#EDF4F1')
MUTED=colors.HexColor('#62716E'); BORDER=colors.HexColor('#D9D9D9')
styles={
 'title':ParagraphStyle('title',fontName='YaHeiBold',fontSize=24,leading=33,textColor=colors.black,spaceAfter=10),
 'subtitle':ParagraphStyle('subtitle',fontName='YaHei',fontSize=10,leading=16,textColor=MUTED,spaceAfter=14),
 'h1':ParagraphStyle('h1',fontName='YaHeiBold',fontSize=15,leading=22,textColor=colors.black,spaceBefore=10,spaceAfter=6,keepWithNext=True),
 'h2':ParagraphStyle('h2',fontName='YaHeiBold',fontSize=11.3,leading=17,textColor=colors.black,spaceBefore=8,spaceAfter=3,keepWithNext=True),
 'body':ParagraphStyle('body',fontName='YaHei',fontSize=10.5,leading=16.5,textColor=INK,spaceAfter=6,wordWrap='CJK'),
 'small':ParagraphStyle('small',fontName='YaHei',fontSize=9,leading=14,textColor=MUTED,spaceAfter=6,wordWrap='CJK'),
 'cell':ParagraphStyle('cell',fontName='YaHei',fontSize=9.5,leading=15,textColor=INK,wordWrap='CJK'),
 'th':ParagraphStyle('th',fontName='YaHeiBold',fontSize=9.5,leading=15,textColor=colors.white,wordWrap='CJK'),
}
story=[];md=[]
def para(text,style='body'):
 story.append(Paragraph(escape(text),styles[style]));md.append(text+'\n')
def heading(text,level=1):
 story.append(Paragraph(escape(text),styles['h'+str(level)]));md.append('#'*(level+1)+' '+text+'\n')
def title(text,subtitle):
 para(text,'title');para(subtitle,'subtitle')
def step(label,text):
 story.append(KeepTogether([Paragraph(escape(label),styles['h2']),Paragraph(escape(text),styles['body'])]))
 md.extend(['### '+label+'\n',text+'\n'])
def table(headers,rows,widths):
 data=[[Paragraph(escape(c),styles['th']) for c in headers]]
 data.extend([[Paragraph(escape(c),styles['cell']) for c in row] for row in rows])
 t=Table(data,colWidths=[w*mm for w in widths],repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),GREEN),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]),
  ('GRID',(0,0),(-1,-1),.55,BORDER),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
  ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),
  ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
 story.extend([t,Spacer(1,8)])
 md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |')
 md.extend('| '+' | '.join(row)+' |' for row in rows);md.append('')
def callout(text):
 t=Table([[Paragraph(escape(text),styles['body'])]],colWidths=[170*mm])
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE),('BOX',(0,0),(-1,-1),.6,BORDER),
  ('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
 story.extend([t,Spacer(1,5)]);md.append('> '+text+'\n')

title('Reachy 游戏陪玩助手用户指南','英雄联盟陪玩版   |   2026 年 9 月   |   01 快速开始')
para('这份指南帮助你连接 Reachy Mini、开始语音陪伴，并使用英雄出装和装备知识。完成首次设置后，日常只需打开页面，确认连接，再点击“开始陪伴”。未开局时也可以聊天。')
callout('本机使用入口  http://127.0.0.1:8768/\n这是当前电脑的本地页面，需要陪玩服务保持运行；其他电脑不能通过这个地址访问。')
heading('首次使用按这六步操作')
step('1 连接机器人','接好 Reachy Mini 的电源和 USB，打开 Reachy Mini Control 并等待本体就绪。在陪玩页面进入“设备与连接”，点击“连接本体”，确认页面显示“Reachy 已连接”。')
step('2 检查声音和动作','在尚未开始陪玩时，使用“测试本体声音”“收音 3 秒”和“轻轻点头”检查设备。声音和动作需要你现场确认；声音测试使用测试音，试听所选声线请使用声音卡片上的“本体试听”。')
step('3 设置你的搭子','修改搭子的名字，选择声线并试听，调整本体音量。反应强度可选“安静陪伴”“恰到好处”或“热闹一点”。完成后点击“保存设置”。建议先用“恰到好处”。')
step('4 开始陪伴','点击“开始陪伴”。页面显示收听状态后，可以直接开口。第一次试说：“默默，你能听到我吗？”如果改过名字，请换成你设置的称呼。')
step('5 接入游戏画面','进入实际对局后，在“设备与连接”中选择英雄联盟游戏窗口，点击“使用此窗口”，再切回游戏。当前版本只采集选中的前台游戏窗口；只有大厅时，先进入对局。')
step('6 核对本局英雄','在“本局身份与朋友”中查看识别结果；不对就点击“读取本局玩家”，选择自己并确认。没有名册时，可在游戏保持前台、采集正常的情况下说“默默，这局我玩奇亚娜”，或填写本局自报。')
para('开局后可在“设备与连接”查看“本局出装攻略”“长期装备记忆”和“情绪动作预设”的加载状态。','small')

story.append(PageBreak());md.append('\n---\n')
title('和搭子自然互动','02 语音互动与出装')
para('说话时先叫搭子的名字，或明确向它提问，更容易被识别为对助手说话。游戏播报、队内报点和没有明确对象的短句可能被忽略。它会优先接住你的情绪，提问时再给具体内容。')
heading('可以直接这样说')
table(['你想做什么','示例说法'],[
 ('吐槽或寻求安慰','“默默，喊了半天都没人跟，我真的很气。”'),
 ('分享高光','“默默，刚才这波太爽了！”'),
 ('问本局出装','“默默，奇亚娜中单先出什么，后面怎么补？”'),
 ('问装备昵称和效果','“默默，金身是什么？什么时候用比较好？”'),
 ('暂时专心打游戏','“默默，先安静一下。”'),
 ('恢复聊天或调音量','“默默，可以继续说话了。” / “默默，小声一点。”'),
],[38,132])
heading('出装攻略会提前准备')
para('确认你的本局英雄后，助手会后台加载 OP.GG 出装资料，包括核心装备、鞋子和加点参考。尚未明确分路时，会准备常见分路的攻略；提问时说清“中单”“打野”等位置，有助于选择对应内容。')
para('你可以继续追问“这件装备有什么用”“第二件为什么这样选”。攻略按来源版本提供参考，游戏更新、对局模式和实际阵容可能影响选择。资料暂时加载失败时，可以先问已有的装备知识。')
heading('哪些信息会被记住')
table(['记忆类型','保存内容与保留方式'],[
 ('本局临时记忆','当前英雄、阵容资料、出装攻略和本次互动上下文；结束会话后清除，不把上局攻略当成本局答案。'),
 ('本地长期记忆','装备名称、常见昵称和效果；保存在本机，重启后仍可查询。启动时检查资料是否需要更新。'),
],[38,132])
heading('机器人会怎样回应')
para('助手可配合语音选择点头、安抚、惊讶、开心或庆祝等 HF 社区动作。动作自带音效已关闭，避免盖住说话；它不会每句话都动，动作忙碌或未加载时也可能只说话。')

story.append(PageBreak());md.append('\n---\n')
title('控制陪伴节奏','03 设置与常见问题')
table(['操作','适合什么时候使用'],[
 ('安静陪着','只想专心玩一会儿。继续观察和收听，停止主动评论；想恢复时点击“恢复回应”。'),
 ('暂停采集','暂时不想收音或采集游戏画面。恢复时点击“恢复采集”。'),
 ('结束','本次陪玩结束。停止采集并清空本次上下文；已保存设置和长期装备知识仍保留。'),
 ('立即停止','想立刻打断正在进行的语音或动作。在“设备与连接”的“本体检查”区域点击。'),
],[38,132])
heading('常见问题')
step('叫它没有回答','先看是否已经开始陪伴、是否暂停，以及“刚才听到”有没有识别文字。清楚叫出搭子的名字再问一次。收音仍无反应时，结束陪玩后检查 Reachy 音频设备，并运行“收音 3 秒”。')
step('听不到声音或声线没有变化','检查本体音量和所选声线是否已配置，修改后点击“保存设置”。结束陪玩后再“本体试听”。切换输入或输出设备也需要先结束陪玩。')
step('它不知道我在玩谁或出什么','先确认本局身份，再查看“本局出装攻略”的状态。提问时补充英雄和位置。接口没有名册时可自报英雄；切出游戏或暂停后，自报身份可能需要重新确认。')
step('机器人没有动作','先查看“情绪动作预设”是否已加载。普通回答不一定配动作；需要检查硬件时，结束陪玩后使用“轻轻点头”。动作加载数量不等于每个动作都已经现场确认。')
step('页面提示本地服务未连接','先刷新当前页面，尤其是在服务刚更新或重启之后。仍不能连接时，需要重新启动本机陪玩服务；修改声音或反应设置不能解决服务离线。')
heading('设置与数据')
para('可在“反应设置”中调整事件回应，再保存设置。需要改变机器人朝向时，先结束陪玩，再进入“座位方向”调整并保存。')
para('开始后，选定的游戏画面和麦克风语音会按需交给已配置的模型服务，摄像头不参与。“结束并清除本地记录”会删除本地会话缓存、用量和运行日志，保留设置及长期装备知识；不会删除云端服务留存或独立验收文件。','small')

def decorate(canvas,doc):
 canvas.saveState()
 canvas.setFillColor(GREEN);canvas.rect(20*mm,282*mm,10*mm,2*mm,fill=1,stroke=0)
 canvas.setFont('YaHei',8);canvas.setFillColor(MUTED)
 canvas.drawString(20*mm,13*mm,'Reachy 游戏陪玩助手  ·  用户指南')
 canvas.drawRightString(190*mm,13*mm,f'{doc.page} / 3')
 canvas.restoreState()

path=OUT/'Reachy游戏陪玩助手用户指南.pdf'
doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=22*mm,bottomMargin=22*mm,
 title='Reachy 游戏陪玩助手用户指南',author='Reachy 游戏陪玩助手',subject='快速开始 语音互动 出装知识 常见问题')
doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
pages=PdfReader(str(path)).pages
assert len(pages)==3, f'Expected 3 pages, got {len(pages)}'
(OUT/'Reachy游戏陪玩助手用户指南.md').write_text('# Reachy 游戏陪玩助手用户指南\n\n'+'\n'.join(md),encoding='utf8')
print(f'Created {len(pages)} pages: {path}')
for n,p in enumerate(pages,1):print('page',n,'characters',len(p.extract_text()))
