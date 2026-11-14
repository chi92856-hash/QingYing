"""Presentation layer for the Qingying desktop application."""
import tkinter as tk
import customtkinter as ctk

from mac_theme import T, icon
BG=T['paper'];CARD=T['surface'];INK=T['ink'];MUTED=T['muted'];ACCENT=T['accent'];PALE=T['selected'];NAV=T['sidebar']

def components():
    font=lambda size=13,weight='normal': ctk.CTkFont(family='Microsoft YaHei UI',size=max(13,size),weight=weight)
    def label(parent,text,**kw):
        return ctk.CTkLabel(parent,text=text,font=kw.pop('font',font()),text_color=kw.pop('text_color',INK),**kw)
    def button(parent,text,command,primary=False,**kw):
        return ctk.CTkButton(parent,text=text,command=command,font=font(),height=36,corner_radius=7,
            border_width=0 if primary else 1,border_color=T['rule'],
            fg_color=ACCENT if primary else CARD,hover_color=T['accent_hover'] if primary else T['hover'],
            text_color=CARD if primary else INK,**kw)

    return font,label,button

def build_ui(app):
    font,label,button=components()
    app.grid_columnconfigure(1,weight=1)
    app.grid_rowconfigure(0,weight=1)
    sidebar=ctk.CTkFrame(app,width=208,corner_radius=0,fg_color=NAV)
    sidebar.grid(row=0,column=0,sticky='nsew')
    sidebar.grid_propagate(False)
    sidebar.grid_columnconfigure(0,weight=1)
    sidebar.grid_rowconfigure(8,weight=1)
    brand=ctk.CTkFrame(sidebar,fg_color='transparent');brand.grid(row=0,column=0,padx=20,pady=(26,2),sticky='ew')
    label(brand,'',image=icon('brand',ACCENT,27)).pack(side='left',padx=(0,10))
    label(brand,'清影',font=font(23,'bold')).pack(side='left')
    label(sidebar,'素材工具',font=font(12),text_color=MUTED,anchor='w').grid(row=1,column=0,padx=58,pady=(0,26),sticky='ew')
    for row,key,title in [(3,'download','链接下载'),(4,'edit','水印修复'),(5,'collector','小红书采集'),(6,'facebook','Facebook 主页'),(7,'x','X 图片')]:
        nav=ctk.CTkButton(sidebar,text=title,image=icon(key,MUTED,19),compound='left',height=42,corner_radius=8,anchor='w',font=font(14),
            border_width=0,fg_color='transparent',hover_color=T['hover'],text_color=INK,command=lambda name=key:app.show_page(name))
        nav.grid(row=row,column=0,padx=12,pady=4,sticky='ew');setattr(app,'nav_'+key,nav)
    label(sidebar,'文件保存在本机',font=font(12),text_color=MUTED,anchor='w').grid(row=9,column=0,padx=22,pady=12,sticky='ew')
    from updater import VERSION, check_from_ui
    label(sidebar,f'版本 {VERSION}',font=font(12),text_color=MUTED,anchor='w').grid(row=10,column=0,padx=22,pady=(0,6),sticky='ew')
    button(sidebar,'检查更新',lambda:check_from_ui(app)).grid(row=11,column=0,padx=16,pady=(0,16),sticky='ew')

    main=ctk.CTkFrame(app,fg_color=BG,corner_radius=0)
    main.grid(row=0,column=1,sticky='nsew',padx=28,pady=22)
    main.grid_columnconfigure(0,weight=1)
    main.grid_rowconfigure(2,weight=1)
    header=ctk.CTkFrame(main,fg_color='transparent')
    header.grid(row=0,column=0,sticky='ew',pady=(0,16))
    heading=ctk.CTkFrame(header,fg_color='transparent')
    heading.pack(side='left')
    app.page_title=label(heading,'链接下载',font=font(25,'bold'))
    app.page_title.pack(anchor='w')
    app.page_subtitle=label(heading,'',font=font(11),text_color=MUTED)
    app.page_subtitle.pack(anchor='w',pady=(2,0))
    app.activity=label(header,'就绪',font=font(12),text_color=MUTED)
    app.activity.pack(side='right')
    output=ctk.CTkFrame(main,fg_color=CARD,corner_radius=13,border_width=1,border_color='#E8ECF3')
    app.output_panel=output
    output.grid(row=1,column=0,sticky='ew',pady=(0,14))
    label(output,'保存位置',font=font(12,'bold')).pack(side='left',padx=(16,12),pady=14)
    app.folder_entry=ctk.CTkEntry(output,textvariable=app.folder,height=34,border_width=0,fg_color='#F4F6FA',font=font(11))
    app.folder_entry.pack(side='left',fill='x',expand=True,pady=14)
    app.folder_btn=button(output,'更改',app.select_folder,width=58)
    app.folder_btn.pack(side='left',padx=8)
    button(output,'打开文件夹',app.open_folder,width=90).pack(side='left',padx=(0,14))

    app.pages={}
    for key in ['download','edit','collector','facebook','x']:
        frame=ctk.CTkFrame(main,fg_color=BG if key=='facebook' else CARD,corner_radius=10,border_width=0 if key=='facebook' else 1,border_color=T['rule'])
        frame.grid(row=2,column=0,sticky='nsew')
        app.pages[key]=frame
    download=app.pages['download']
    download.grid_columnconfigure(0,weight=1)
    download.grid_rowconfigure(1,weight=1)
    intro=ctk.CTkFrame(download,fg_color='transparent')
    intro.grid(row=0,column=0,sticky='ew',padx=22,pady=(18,10))
    label(intro,'作品链接',font=font(16,'bold')).pack(side='left')
    label(intro,'X',font=font(11),fg_color='#EFF1F6',corner_radius=6,width=28,height=23).pack(side='right')
    label(intro,'Facebook',font=font(11),text_color='#3266B0',fg_color='#EDF4FF',corner_radius=6,width=78,height=23).pack(side='right',padx=(6,0))
    label(intro,'Instagram',font=font(11),text_color='#A34F9F',fg_color='#FBEFFA',corner_radius=6,width=82,height=23).pack(side='right',padx=(6,0))
    label(intro,'抖音',font=font(11),fg_color='#EFF1F6',corner_radius=6,width=45,height=23).pack(side='right',padx=(6,0))
    label(intro,'小红书',font=font(11),text_color='#D95A72',fg_color='#FFF0F3',corner_radius=6,width=58,height=23).pack(side='right')
    input_frame=ctk.CTkFrame(download,fg_color='#F6F7FB',corner_radius=11,border_width=1,border_color='#E6EAF3')
    input_frame.grid(row=1,column=0,sticky='nsew',padx=22)
    label(input_frame,'粘贴作品链接或分享文案，支持一次添加多条',font=font(12),text_color=MUTED).pack(anchor='w',padx=14,pady=(9,0))
    app.links=ctk.CTkTextbox(input_frame,height=104,fg_color='transparent',font=font(13),text_color=INK,wrap='word',border_spacing=12)
    app.links.pack(fill='both',expand=True,padx=2,pady=(0,4))
    row=ctk.CTkFrame(download,fg_color='transparent')
    row.grid(row=2,column=0,sticky='ew',padx=22,pady=10)
    label(row,'',textvariable=app.notice,font=font(11),text_color=MUTED,wraplength=400,justify='left').pack(side='left')
    app.paste_btn=button(row,'粘贴剪贴板',app.paste,width=110)
    app.paste_btn.pack(side='right')
    app.resume_btn=button(row,'继续待下载',app.resume_download,width=108)
    app.resume_btn.configure(state='normal' if app.pending_urls else 'disabled')
    app.resume_btn.pack(side='right',padx=(0,7))
    options=ctk.CTkFrame(download,fg_color='#F7F8FC',corner_radius=10)
    options.grid(row=3,column=0,sticky='ew',padx=22,pady=(0,10))
    option_text=ctk.CTkFrame(options,fg_color='transparent')
    option_text.pack(side='left',padx=14,pady=10)
    label(option_text,'是否静音',font=font(13,'bold')).pack(anchor='w')
    label(option_text,'开启后移除视频音轨，画质保持不变',font=font(11),text_color=MUTED).pack(anchor='w',pady=(1,0))
    app.mute_check=ctk.CTkSwitch(options,text='静音保存',variable=app.mute,font=font(12),text_color=INK,progress_color=ACCENT,button_color='white',button_hover_color='#EFF1FF',width=105)
    app.mute_check.pack(side='right',padx=18)
    auth=ctk.CTkFrame(download,fg_color='transparent')
    auth.grid(row=4,column=0,sticky='ew',padx=22,pady=(0,12))
    label(auth,'登录凭证（可选）',font=font(11),text_color=MUTED).pack(side='left')
    app.cookie_entry=ctk.CTkEntry(auth,textvariable=app.cookie,state='readonly',height=28,font=font(10),border_width=0,fg_color='#F4F6FA')
    app.cookie_entry.pack(side='left',fill='x',expand=True,padx=8)
    app.cookie_btn=button(auth,'Cookies.txt',app.select_cookie,width=92)
    app.cookie_btn.pack(side='left')
    app.cookie_clear=button(auth,'清除',lambda:app.cookie.set(''),width=52)
    app.cookie_clear.pack(side='left',padx=(6,0))
    app.instagram_btn=button(auth,'Instagram 登录',app.instagram_login,width=126)
    app.instagram_btn.pack(side='left',padx=(6,0))
    end=ctk.CTkFrame(download,fg_color='transparent')
    end.grid(row=5,column=0,sticky='ew',padx=22,pady=(0,18))
    label(end,'保存平台可用源文件；画面自带的标志可用水印修复处理。',font=font(11),text_color=MUTED).pack(side='left')
    app.download_btn=button(end,'解析并保存',app.start_download,primary=True,width=166)
    app.download_btn.pack(side='right')

    foot=ctk.CTkFrame(main,fg_color=CARD,corner_radius=13,border_width=1,border_color='#E8ECF3')
    foot.grid(row=3,column=0,sticky='ew',pady=(14,0))
    status_row=ctk.CTkFrame(foot,fg_color='transparent')
    status_row.pack(fill='x',padx=16,pady=(10,0))
    label(status_row,'任务进度',font=font(12,'bold')).pack(side='left')
    label(status_row,'',textvariable=app.status,font=font(11),text_color=MUTED,wraplength=560,anchor='w').pack(side='left',padx=12)
    app.stop_btn=button(status_row,'取消',app.stop,width=58)
    app.stop_btn.configure(state='disabled')
    app.stop_btn.pack(side='right')
    app.progress=ctk.CTkProgressBar(foot,height=4,fg_color='#ECF0F7',progress_color=ACCENT)
    app.progress.set(0)
    app.progress.pack(fill='x',padx=16,pady=(7,3))
    app.logbox=ctk.CTkTextbox(foot,height=58,state='disabled',fg_color='transparent',font=font(10),text_color=MUTED,wrap='word',border_spacing=5)
    app.logbox.pack(fill='x',padx=11,pady=(0,7))
    app.lock_controls=[app.folder_entry,app.folder_btn,app.paste_btn,app.download_btn,app.cookie_btn,app.cookie_clear,app.mute_check,app.instagram_btn]
    app.show_page('download')
    app.add_log('准备就绪。粘贴分享链接，或切换到水印修复。')


def build_editor(app):
    font,label,button=components()
    edit=app.pages['edit']
    edit.grid_columnconfigure(0,weight=1)
    edit.grid_rowconfigure(2,weight=1)
    top=ctk.CTkFrame(edit,fg_color='transparent')
    top.grid(row=0,column=0,sticky='ew',padx=20,pady=(16,8))
    app.file_label=label(top,'选择文件，框选水印',font=font(16,'bold'))
    app.file_label.pack(side='left')
    app.file_btn=button(top,'＋  选择图片 / 视频',app.select_media,width=156)
    app.file_btn.pack(side='right')
    label(edit,'拖动框选，可添加多个区域。视频选框作用于整段画面，不会自动跟踪。',font=font(11),text_color=MUTED).grid(row=1,column=0,sticky='w',padx=20,pady=(0,8))
    app.canvas=tk.Canvas(edit,bg='#EDF0F7',highlightthickness=0,height=175,cursor='crosshair')
    app.canvas.grid(row=2,column=0,sticky='nsew',padx=20)
    app.canvas.bind('<Configure>',lambda e:app.schedule_draw())
    app.canvas.bind('<ButtonPress-1>',app.press)
    app.canvas.bind('<B1-Motion>',app.drag)
    app.canvas.bind('<ButtonRelease-1>',app.release)
    app.slider=ctk.CTkSlider(edit,from_=0,to=99,variable=app.video_pos,command=app.seek,progress_color=ACCENT,button_color=ACCENT,height=16,state='disabled')
    app.slider.grid(row=3,column=0,sticky='ew',padx=22,pady=9)
    actions=ctk.CTkFrame(edit,fg_color='transparent')
    actions.grid(row=4,column=0,sticky='ew',padx=20,pady=(0,8))
    app.undo_btn=button(actions,'撤销',app.undo,width=58)
    app.undo_btn.pack(side='left')
    app.clear_btn=button(actions,'清空',app.clear,width=58)
    app.clear_btn.pack(side='left',padx=6)
    app.preview_btn=button(actions,'图片效果预览',app.preview,width=110)
    app.preview_btn.pack(side='left')
    app.export_btn=button(actions,'修复并保存',app.start_restore,primary=True,width=152)
    app.export_btn.pack(side='right')
    label(edit,'图片保存为 PNG，视频保存为 MP4 并保留音轨。复杂背景可能留痕。',font=font(11),text_color=MUTED).grid(row=5,column=0,sticky='w',padx=20,pady=(0,14))

    controls=[app.file_btn,app.undo_btn,app.clear_btn,app.preview_btn,app.export_btn]
    app.lock_controls.extend(controls)
    for widget in controls:widget.configure(state='disabled' if app.busy else 'normal')
