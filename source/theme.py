"""Hallmark v2.0.0 | Rim night | native app theme tokens.
Full redesign; shell kept; signature: link workspace and persistent task log.
Chinese system font replaces Switzer for complete offline CJK coverage.
CSS-only layout gates do not apply to native Tk; no decorative motion.
"""
import customtkinter as ctk

# Declared theme block: all presentation colours and fonts live here.
T={
    'paper':'#171715', 'panel':'#1E1E1B', 'nav':'#111210',
    'well':'#141512', 'raised':'#292A25', 'hover':'#34362F',
    'ink':'#EEEDE6', 'secondary':'#CFD0C6', 'muted':'#A2A69A',
    'disabled':'#7E8376', 'rule':'#3C4036', 'field_border':'#737B69',
    'accent':'#F28D50', 'accent_hover':'#FFA86F', 'accent_ink':'#21160E',
    'selection':'#393027', 'focus':'#FFC18A', 'secondary_signal':'#94BADE',
    'error':'#F2A48F', 'transparent':'transparent',
    'font':'Microsoft YaHei UI', 'number_font':'Consolas'
}
BG=T['paper'];CARD=T['panel'];INK=T['ink'];MUTED=T['muted']
ACCENT=T['accent'];PALE=T['raised'];NAV=T['nav']


def install_theme():
    ctk.set_appearance_mode('dark')
    theme=ctk.ThemeManager.theme
    for name,options in theme.items():
        if not isinstance(options,dict):continue
        for key in list(options):
            if key.endswith('color') or key.endswith('color_disabled'):
                if 'disabled' in key:options[key]=T['disabled']
                elif key in ('text_color','label_text_color'):options[key]=INK
                elif key=='placeholder_text_color':options[key]=MUTED
                elif key=='checkmark_color':options[key]=T['accent_ink']
                elif key in ('progress_color',):options[key]=ACCENT
                elif key=='border_color':options[key]=T['field_border']
                elif 'hover' in key:options[key]=T['hover']
                elif key=='button_color':options[key]=T['secondary']
                elif key=='fg_color':options[key]=T['panel']
        if 'corner_radius' in options:options['corner_radius']=0
    for name in ('CTk','CTkToplevel'):theme[name]['fg_color']=BG
    theme['CTkLabel'].update(fg_color='transparent')
    theme['CTkScrollbar'].update(fg_color='transparent',button_color=T['rule'],button_hover_color=T['field_border'])
    theme['CTkFrame'].update(fg_color=CARD,top_fg_color=CARD,border_color=T['rule'])
    theme['CTkButton'].update(fg_color=PALE,hover_color=T['hover'],border_width=1,border_color=T['rule'])
    theme['CTkEntry'].update(fg_color=T['well'],border_width=1)
    theme['CTkTextbox'].update(fg_color=T['well'],border_width=1,border_color=T['field_border'])
    theme['CTkSwitch'].update(fg_color=T['field_border'],button_color=INK,button_hover_color=INK,progress_color=ACCENT,border_width=0)
    theme['CTkCheckBox'].update(fg_color=ACCENT,hover_color=T['accent_hover'],border_width=2)
    theme['CTkProgressBar'].update(fg_color=T['rule'],progress_color=ACCENT)
    theme['CTkSlider'].update(progress_color=ACCENT,button_color=ACCENT)
    for name in ('CTkOptionMenu','CTkComboBox'):
        theme[name].update(fg_color=PALE,button_color=T['hover'],button_hover_color=T['rule'])
    for osname,options in theme.get('CTkFont',{}).items():
        if isinstance(options,dict):options['family']=T['font']


def install_focus(root):
    """Instant keyboard focus feedback on native controls, without animations."""
    def walk(widget):
        if isinstance(widget,(ctk.CTkButton,ctk.CTkEntry,ctk.CTkTextbox,ctk.CTkSwitch,ctk.CTkCheckBox,ctk.CTkOptionMenu)) and not getattr(widget,'_qingying_focus',False):
            widget._qingying_focus=True
            if isinstance(widget,(ctk.CTkButton,ctk.CTkEntry,ctk.CTkTextbox)):
                baseline=widget.cget('border_color')
                widget.bind('<FocusIn>',lambda e,w=widget:w.configure(border_color=T['focus']),add='+')
                widget.bind('<FocusOut>',lambda e,w=widget,b=baseline:w.configure(border_color=b),add='+')
            if isinstance(widget,ctk.CTkButton):
                widget._canvas.configure(takefocus=1)
                widget._canvas.bind('<Return>',lambda e,w=widget:w.invoke(),add='+')
                widget._canvas.bind('<space>',lambda e,w=widget:w.invoke(),add='+')
        for child in widget.winfo_children():walk(child)
    walk(root)
