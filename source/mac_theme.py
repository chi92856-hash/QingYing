"""Native macOS-inspired light presentation; no web assets or remote fonts."""
import customtkinter as ctk
T={'paper':'#F7F8FA','sidebar':'#EDEFF3','surface':'#FFFFFF','ink':'#202126',
   'muted':'#737780','rule':'#E0E3E9','field':'#FCFCFD','accent':'#007AFF',
   'accent_hover':'#006BE0','selected':'#D9E9FF','hover':'#E4E7ED','disabled':'#969BA5',
   'font':'Microsoft YaHei UI'}

def install_theme():
    ctk.set_appearance_mode('light')
    theme=ctk.ThemeManager.theme
    theme['CTk'].update(fg_color=T['paper'])
    theme['CTkToplevel'].update(fg_color=T['paper'])
    theme['CTkFrame'].update(fg_color=T['surface'],top_fg_color=T['surface'],border_color=T['rule'])
    theme['CTkLabel'].update(text_color=T['ink'],fg_color='transparent')
    theme['CTkEntry'].update(fg_color=T['field'],border_color=T['rule'],text_color=T['ink'],placeholder_text_color=T['muted'],border_width=1,corner_radius=7)
    theme['CTkButton'].update(fg_color=T['surface'],hover_color=T['hover'],text_color=T['ink'],text_color_disabled=T['disabled'],border_color=T['rule'],border_width=1,corner_radius=7)
    theme['CTkSwitch'].update(fg_color='#D8DBE1',progress_color=T['accent'],button_color=T['surface'],button_hover_color=T['surface'],text_color=T['ink'],text_color_disabled=T['disabled'],border_width=0,corner_radius=1000)
    theme['CTkCheckBox'].update(fg_color=T['accent'],hover_color=T['accent_hover'],text_color=T['ink'],border_color=T['disabled'])
    theme['CTkProgressBar'].update(fg_color=T['rule'],progress_color=T['accent'])
    theme['CTkSlider'].update(progress_color=T['accent'],button_color=T['accent'],button_hover_color=T['accent_hover'])
    theme['CTkOptionMenu'].update(fg_color=T['sidebar'],button_color=T['hover'],button_hover_color=T['rule'],text_color=T['ink'])
    theme['CTkScrollbar'].update(button_color='#C9CED7',button_hover_color='#AEB6C3')
    for entry in theme.get('CTkFont',{}).values():
        if isinstance(entry,dict):entry['family']=T['font']


def icon(kind,color,size=20):
    """Small consistent line icons rendered locally at 3x for clean scaling."""
    from PIL import Image,ImageDraw
    scale=3;im=Image.new('RGBA',(size*scale,size*scale));d=ImageDraw.Draw(im)
    def line(points):d.line([(int(x*scale),int(y*scale)) for x,y in points],fill=color,width=2*scale,joint='curve')
    def rect(box,r=2):d.rounded_rectangle(tuple(int(v*scale) for v in box),radius=r*scale,outline=color,width=2*scale)
    if kind=='brand':rect((2,2,13,13));rect((7,7,18,18))
    elif kind=='download':
        line([(8,12),(6,14),(3,14),(2,12),(2,9),(7,4),(10,4),(12,6),(12,8)])
        line([(8,12),(8,14),(10,16),(13,16),(18,11),(18,8),(16,6),(14,6)])
    elif kind=='edit':line([(3,12),(11,3),(17,9),(9,17),(3,12),(3,16),(16,16)])
    elif kind=='collector':rect((3,2,17,18));line([(6,7),(14,7)]);line([(6,11),(12,11)])
    elif kind=='x':line([(4,3),(16,17)]);line([(16,3),(4,17)])
    elif kind=='facebook':
        rect((3,2,17,18),3);line([(12,5),(10,5),(9,7),(9,17)]);line([(6,10),(13,10)])
    return ctk.CTkImage(im,size=(size,size))
