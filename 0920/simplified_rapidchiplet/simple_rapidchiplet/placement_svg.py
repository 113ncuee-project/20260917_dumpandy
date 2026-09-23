"""Standalone SVG export of the same physical placement/routes shown in the GUI."""
from xml.etree.ElementTree import Element, SubElement, tostring

COLORS = ("#4f76ce", "#1c9c95", "#9c78cc", "#d0a04f", "#c87993", "#658d50")


def render_placement_svg(result, selection="physical"):
    c=result['best_candidate']
    if c is None:
        raise ValueError('No admissible placement to export')
    graph=c['connection_graph'];w=c['effective_hardware']['chiplet']['width_mm']
    nodes={n['id']:n for n in graph['nodes']}
    xmax=max(n['x'] for n in nodes.values())+w
    ymax=max(n['y'] for n in nodes.values())+w
    root=Element('svg',xmlns='http://www.w3.org/2000/svg',width='1000',height=str(1000*(ymax+2.2)/(xmax+2.2)),
                 viewBox=f'-1.1 -1.1 {xmax+2.2} {ymax+2.2}')
    SubElement(root,'title').text=f"{result['model']} — actual chiplet placement (mm), traffic: {selection}"
    SubElement(root,'desc').text='Physical coordinates and routed unicast flows from the evaluated candidate; fixed mesh.'
    defs=SubElement(root,'defs')
    marker=SubElement(defs,'marker',id='arrow',viewBox='0 0 10 10',refX='8',refY='5',markerWidth='5',markerHeight='5',orient='auto-start-reverse')
    SubElement(marker,'path',d='M 0 0 L 10 5 L 0 10 z',fill='#2d59d0')
    groups={};cursor=0
    for group in c['mapping_plan']['groups']:
        for _ in range(group['chiplets']):
            groups[cursor]=group;cursor+=1
    for node in nodes.values():
        color=COLORS[groups[node['id']]['group_index']%len(COLORS)]
        rect=SubElement(root,'rect',x=str(node['x']),y=str(node['y']),width=str(w),height=str(w),rx='.18',
                        fill=color,stroke=color,**{'fill-opacity':'.22','stroke-width':'.035','data-chiplet':str(node['id'])})
        SubElement(rect,'title').text=f"C{node['id']} ({node['x']}, {node['y']}) mm: {node['stage']}"
    def point(n):return nodes[n]['x']+w/2,nodes[n]['y']+w/2
    for edge in graph['physical_links']:
        x1,y1=point(edge['source']);x2,y2=point(edge['target'])
        SubElement(root,'line',x1=str(x1),y1=str(y1),x2=str(x2),y2=str(y2),stroke='#7d90a9',**{'stroke-width':'.055'})
    if selection=='physical':flows=[]
    elif selection=='all':flows=graph['routed_traffic']
    elif selection.isdecimal() and int(selection)<len(c['communication_events']):
        flows=c['communication_events'][int(selection)]['flows']
    else:raise ValueError('Invalid traffic event')
    for flow in flows:
        points=' '.join(f'{point(n)[0]},{point(n)[1]}' for n in flow['path'])
        SubElement(root,'polyline',points=points,fill='none',stroke='#2d59d0',**{'stroke-opacity':'.78','stroke-width':'.14','marker-end':'url(#arrow)'})
    for n in nodes.values():
        cx,cy=point(n['id']);g=groups[n['id']]
        SubElement(root,'circle',cx=str(cx),cy=str(cy),r='.10',fill='white',stroke='#7289a5',**{'stroke-width':'.06'})
        labels=((1.35,f"C{n['id']}",'.76'),(w-1.35,f"G{g['group_index']} · {g['strategy']}",'.42'),
                (w-.60,f"{n['x']:.2f}, {n['y']:.2f} mm",'.46'))
        for y,text,size in labels:
            SubElement(root,'text',x=str(n['x']+.65),y=str(n['y']+y),fill='#263f5c',
                       **{'font-family':'Segoe UI, sans-serif','font-size':size}).text=text
    return tostring(root,encoding='utf-8',xml_declaration=True)
