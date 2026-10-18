import html
import json
from pathlib import Path
import shutil

from PIL import Image, ImageDraw, ImageFont, ImageOps
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties


def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc', size)


def fitted(canvas, source, box):
    image = source.copy().convert('RGB')
    image.thumbnail((box[2]-box[0], box[3]-box[1]), Image.Resampling.LANCZOS)
    canvas.paste(image, (int((box[0]+box[2]-image.width)/2), int((box[1]+box[3]-image.height)/2)))


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--task', type=Path, required=True)
    args=parser.parse_args()
    task=args.task
    summary = json.loads((task/'summary.json').read_text())
    target = Path(__file__).resolve().parents[2]/'docs/benchmarks/2026-10-18'
    for directory in ('originals','assembled','pairs','figures','records'):
        (target/directory).mkdir(parents=True, exist_ok=True)
    for name in ('summary.json','green-cases.json','exclusions.json','all-trials.csv','per-image.csv'):
        shutil.copy2(task/name,target/name)
    colors = {'VERIFIED':'#067D70','AMBIGUOUS':'#A86A08','GEOMETRY_ONLY':'#9C4856','BEST':'#547086'}
    descriptions = {'VERIFIED':'通过自动执行规则','AMBIGUOUS':'存在歧义  需确认','GEOMETRY_ONLY':'仅几何候选','BEST':'普通模式保底布局'}
    panels=[]
    cards=[]
    for row in summary['cases']:
        name=row['capture']; ident=row['id']
        source=task/'originals'/(name+'_raw.png')
        assembled=task/(row['representative_path']+'.png')
        shutil.copy2(source,target/'originals'/(name+'_raw.png'))
        shutil.copy2(assembled,target/'assembled'/(name+'.png'))
        shutil.copy2(task/(row['representative_path']+'.json'), target/'records'/(name+'.json'))
        raw=Image.open(source).convert('RGB'); result=Image.open(assembled).convert('RGB')
        x,y,w,h=row['roi']; roi=raw.crop((x,y,x+w,y+h))
        panel=Image.new('RGB',(1440,640),'white'); d=ImageDraw.Draw(panel)
        d.text((24,13),ident+'  '+name,font=font(29,True),fill='#172A3A')
        d.text((920,20),descriptions[row['status']],font=font(23,True),fill=colors[row['status']])
        for left,right,title in ((24,350,'原始实拍图'),(382,860,'原图 ROI'),(892,1416,'算法拼接预览')):
            d.rounded_rectangle((left,60,right,572),radius=12,fill='#F2F5F7')
            d.text((left+14,72),title,font=font(22),fill='#435467')
        fitted(panel,raw,(34,111,340,560)); fitted(panel,roi,(392,111,850,560)); fitted(panel,result,(902,111,1406,560))
        t=row['timings_ms']
        text=f"{row['mode']}  |  {row['piece_count']} 片  |  检测 {t['detect']['median']:.1f} ms  |  求解 {t['solve']['median']/1000:.3f} s  |  总分析 {t['analysis']['median']/1000:.3f} s"
        d.text((24,591),text,font=font(23),fill='#172A3A')
        panel.save(target/'pairs'/(ident+'.png'))
        panels.append(panel)
        cards.append(f'''<article data-kind="{row['mode']}" data-status="{row['status']}"><a href="pairs/{ident}.png"><img loading="lazy" src="pairs/{ident}.png" alt="{ident} 原始照片、ROI及算法拼接结果"></a><div class="detail"><strong>{ident} · {name}</strong><span class="pill" style="color:{colors[row['status']]}">{row['status']}</span><p>总分析中位数 <b>{t['analysis']['median']/1000:.3f} s</b>　范围 {t['analysis']['min']/1000:.3f}–{t['analysis']['max']/1000:.3f} s　峰值 RSS {row['peak_rss_mib']:.1f} MiB</p><p>三次状态与输出图像一致。展示总分析耗时居中的第 {row['representative_run']} 次结果。</p><nav><a href="originals/{name}_raw.png">原始 PNG</a><a href="assembled/{name}.png">拼接 PNG</a><a href="records/{name}.json">原始记录</a></nav></div></article>''')
    for start in range(0,len(panels),4):
        sheet=Image.new('RGB',(1440,640*min(4,len(panels)-start)), '#E8EDF1')
        for i,panel in enumerate(panels[start:start+4]):sheet.paste(panel,(0,i*640))
        sheet.save(task/f"contact-{start//4+1:02d}.jpg",quality=90)
    cards_stats=summary['groups']['cards']['timings_ms']
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>树莓派 5 拼图视觉测试图集</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf2f5;color:#172a3a;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}header,main,footer{max-width:1220px;margin:auto;padding:32px 24px}header{padding-top:54px}h1{font-size:38px;letter-spacing:-1px;line-height:1.25;margin:10px 0}h2{font-size:23px}.eyebrow{color:#067d70;font-weight:700;letter-spacing:2px}.intro{max-width:920px;color:#536575}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:25px}.stat{background:white;padding:18px 22px;border-radius:12px}.stat b{display:block;font-size:32px;color:#067d70}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;background:#edf2f5;padding:16px 0;position:sticky;top:0;z-index:2}select,input{padding:10px;border:1px solid #cbd5df;border-radius:8px;background:white;font:inherit}input{flex:1;min-width:240px}article{background:white;border:1px solid #dce4ea;border-radius:16px;overflow:hidden;margin-bottom:26px;box-shadow:0 5px 15px #172a3a08}article img{width:100%;display:block}.detail{border-top:1px solid #e1e7ec;padding:18px 24px}.detail p{margin:6px 0;color:#536575}.pill{float:right;font-weight:700}a{color:#067d70;text-decoration:none}nav{display:flex;gap:24px}article[hidden]{display:none}footer{color:#536575;border-top:1px solid #ccd7df}.note{background:#fff;padding:18px 24px;border-radius:12px;border-left:4px solid #ae790d}@media(max-width:680px){.stats{grid-template-columns:1fr 1fr}h1{font-size:29px}.detail{font-size:13px}.pill{float:none;display:block}}
</style><header><div class="eyebrow">RASPBERRY PI 5 / 2026.10.18</div><h1>拼图装置视觉测试图集</h1><p class="intro">43 张绿色背景实拍，每张独立运行三次。保留原图、ROI 和原生算法输出；点击图片查看大图，使用下方筛选器检查具体状态。</p><div class="stats"><div class="stat"><b>43</b>绿色图片</div><div class="stat"><b>139</b>总运行次数</div><div class="stat"><b>CARD_MED s</b>扑克总分析中位数</div><div class="stat"><b>31 / 31</b>历史扑克预览一致</div></div><p class="note">33 张扑克中 18 张 VERIFIED、14 张 AMBIGUOUS、1 张 GEOMETRY_ONLY；10 张普通拼图均为 BEST 保底布局。预览不等于机械放置成功，也不代表全体均已通过自动执行规则。</p></header><main><nav><a href="README.md">测试说明</a><a href="per-image.csv">逐图数据 CSV</a><a href="all-trials.csv">139 次原始数据 CSV</a><a href="summary.json">汇总 JSON</a></nav><div class="toolbar"><select id="kind"><option value="">全部模式</option><option>CARD</option><option>NORMAL</option></select><select id="status"><option value="">全部状态</option><option>VERIFIED</option><option>AMBIGUOUS</option><option>GEOMETRY_ONLY</option><option>BEST</option></select><input id="search" placeholder="查找 G 编号或拍摄编号"><span id="count"></span></div>CARDS</main><footer>计时不含导入、图像读取、相机采集、稳定等待、机械运动或文件导出。CARD 求解包含函数内候选预览，NORMAL 总分析包含求解后的主图渲染。统计采用每图三次中位数；原始逐次值均保留。历史照片属于回归集，没有独立物理真值。</footer><script>const kind=document.getElementById('kind'),stateSelect=document.getElementById('status'),search=document.getElementById('search'),count=document.getElementById('count');const rows=[...document.querySelectorAll('article')];function filter(){let n=0;for(const r of rows){r.hidden=Boolean((kind.value&&r.dataset.kind!==kind.value)||(stateSelect.value&&r.dataset.status!==stateSelect.value)||(search.value&&!r.textContent.toLowerCase().includes(search.value.toLowerCase())));if(!r.hidden)n++}count.textContent=n+' / '+rows.length+' 张'}for(const id of ['kind','status','search'])document.getElementById(id).addEventListener('input',filter);filter();</script></html>'''
    (target/'gallery.html').write_text(page.replace('CARD_MED',f"{cards_stats['analysis']['median_of_image_medians']/1000:.3f}").replace('CARDS','\n'.join(cards)),encoding='utf8')
    # A publication figure of all case medians and their three-run ranges.
    fp=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams['font.family']=fp.get_name();plt.rcParams['axes.unicode_minus']=False
    fig,ax=plt.subplots(figsize=(12.6,11.5),layout='constrained')
    rows=summary['cases']; positions=list(range(len(rows)))
    med=[r['timings_ms']['analysis']['median']/1000 for r in rows]
    ax.barh(positions,med,color=[colors[r['status']] for r in rows],height=.7)
    ax.errorbar(med,positions,xerr=[[m-r['timings_ms']['analysis']['min']/1000 for m,r in zip(med,rows)],
                                  [r['timings_ms']['analysis']['max']/1000-m for m,r in zip(med,rows)]],fmt='none',ecolor='#172A3A',capsize=2,lw=.8)
    ax.set_yticks(positions,[r['id']+'  '+('普通' if r['mode']=='NORMAL' else '扑克') for r in rows],fontsize=9)
    ax.invert_yaxis();ax.set_xlabel('总分析时间 / s   柱形为三次中位数，误差线为最小至最大',fontproperties=fp,fontsize=11)
    ax.set_title('43 张绿色实拍图的板端运行时间',fontproperties=fp,fontsize=17,pad=17)
    ax.set_axisbelow(True);ax.grid(axis='x',color='#e0e5ea');ax.spines[['top','right','left']].set_visible(False)
    ax.set_xlim(0,7.4)
    for y,m in zip(positions,med):ax.text(m+.07,y,f'{m:.3f}',va='center',fontsize=8,color='#435467')
    fig.savefig(target/'figures/timing.png',dpi=220);fig.savefig(target/'figures/timing.svg');plt.close(fig)
    # Compact architecture illustration used in both the repository and report.
    architecture=Image.new('RGB',(1720,910),'white');d=ImageDraw.Draw(architecture)
    d.text((45,30),'视觉处理与执行接口',font=font(46,True),fill='#172A3A')
    columns=[(45,395),(465,815),(885,1235),(1305,1675)]
    entries=[('01  采集与检测','UVC / ROI / 绿色分割','轮廓、角点、中心与朝向'),('02  稳定与求解','多帧中值 / 三种模式','模板、几何或扑克联合搜索'),('03  排名与准入','几何 + 图案 + 竞争差值','保留歧义状态与候选预览'),('04  显示与接口','Flutter / 标定 / 串口','本次仅验证软件图片回放')]
    for index,((left,right),(title,line1,line2)) in enumerate(zip(columns,entries)):
        d.rounded_rectangle((left,135,right,355),radius=18,fill='#EFF5F6',outline='#CCDDE0',width=2)
        d.text((left+20,158),title,font=font(29,True),fill='#067D70')
        d.text((left+20,228),line1,font=font(24),fill='#172A3A')
        d.text((left+20,280),line2,font=font(22),fill='#435467')
        if index<3:
            d.line((right+10,244,right+56,244),fill='#8099A8',width=4)
            d.polygon([(right+56,244),(right+43,235),(right+43,253)],fill='#8099A8')
    d.text((45,423),'扑克模式的四类证据',font=font(31,True),fill='#172A3A')
    evidence=[('拼缝连续性','局部墨迹是否接续'),('整牌结构','角标、主体与方向'),('源图断口','被切开的图案是否复合'),('几何约束','覆盖、重叠与边界')]
    for (left,right),(title,subtitle) in zip(columns,evidence):
        d.rounded_rectangle((left,485,right,635),radius=16,fill='#F4F6F8')
        d.text((left+20,510),title,font=font(30,True),fill='#172A3A');d.text((left+20,567),subtitle,font=font(24),fill='#435467')
    d.text((45,705),'回放计时范围：原图解码后 → 检测 → 求解 → 主预览可用',font=font(30,True),fill='#067D70')
    d.text((45,768),'不含相机曝光、多帧等待、界面通信和机构运动；保留原始像素与逐次 JSON 记录。',font=font(27),fill='#435467')
    architecture.save(target/'figures/pipeline.png')
    print('Assets and gallery:',target)


if __name__ == '__main__':
    main()
