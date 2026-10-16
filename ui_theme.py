"""Warm white and blush desktop controls, including a rounded model menu."""
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).parent/'lib'))
import customtkinter as ctk
import native_windows as native

BG='#FCFAF9'
CARD='#FFFFFF'
SOFT='#F8EDF4'
PINK='#D67AAF'
HOVER='#C8689F'
INK='#423B40'
MUTED='#998D96'
LINE='#ECE4E9'

ctk.set_appearance_mode('light')


def button(parent,text,command,primary=False,width=100):
    return ctk.CTkButton(parent,text=text,command=command,width=width,height=34,
        corner_radius=14,font=('Microsoft YaHei UI',13),
        fg_color=PINK if primary else SOFT,hover_color=HOVER if primary else '#F0DFEA',
        text_color='white' if primary else INK,text_color_disabled='#B5A7B0')


class ModelPicker(ctk.CTkButton):
    def __init__(self,parent):
        self.values=[];self.index=-1;self.handler=None;self.menu=None
        super().__init__(parent,text='正在读取模型…  ⌄',width=208,height=34,
            corner_radius=13,fg_color=CARD,hover_color=SOFT,text_color=INK,
            border_width=1,border_color=LINE,font=('Microsoft YaHei UI',12),command=self.open_menu)

    def current(self,index=None):
        if index is None:return self.index
        self.index=index
        if 0<=index<len(self.values):self.configure(text=self.values[index]+'  ⌄')

    def __setitem__(self,key,value):
        if key!='values':raise KeyError(key)
        self.values=list(value)

    def bind(self,sequence=None,command=None,add=True):
        if sequence=='<<ComboboxSelected>>':self.handler=command;return
        return super().bind(sequence,command,add)

    def open_menu(self):
        if not self.values:return
        if self.menu and self.menu.winfo_exists():self.menu.destroy();return
        menu=ctk.CTkToplevel(self);self.menu=menu
        menu.withdraw();menu.overrideredirect(True);menu.attributes('-topmost',True)
        menu.configure(fg_color=CARD)
        panel=ctk.CTkScrollableFrame(menu,width=210,height=min(280,len(self.values)*37),
            corner_radius=15,fg_color=CARD,border_width=1,border_color=LINE)
        panel.pack(fill='both',expand=True)
        for index,value in enumerate(self.values):
            item=ctk.CTkButton(panel,text=value,anchor='w',height=32,corner_radius=10,
                fg_color=SOFT if index==self.index else CARD,text_color=INK,hover_color=SOFT,
                font=('Microsoft YaHei UI',12),command=lambda i=index:self.choose(i))
            item.pack(fill='x',padx=3,pady=2)
        menu.update_idletasks()
        width,height=menu.winfo_reqwidth(),menu.winfo_reqheight()
        x,y=self.winfo_rootx(),self.winfo_rooty()+self.winfo_height()+5
        left,top,right,bottom=native.work_area(x,y)
        x=max(left,min(x,right-width-8));y=max(top,min(y,bottom-height-8))
        menu.geometry(f'{width}x{height}+{x}+{y}');menu.deiconify()
        native.round_window(native.ancestor(menu.winfo_id(),2),width,height,16)
        menu.bind('<Escape>',lambda event:menu.destroy())
        menu.bind('<FocusOut>',lambda event:menu.after(120,self.close_menu))
        menu.focus_force()

    def close_menu(self):
        if self.menu and self.menu.winfo_exists():self.menu.destroy()

    def choose(self,index):
        self.current(index);self.close_menu()
        if self.handler:self.handler(None)


def build_dashboard(app,background):
    root=ctk.CTk();app.root=root
    if background:root.withdraw()
    root.title('GPT 划词翻译');root.geometry('720x740');root.minsize(640,680)
    root.configure(fg_color=BG);root.protocol('WM_DELETE_WINDOW',app.hide)
    body=ctk.CTkFrame(root,fg_color='transparent',corner_radius=0)
    body.pack(fill='both',expand=True,padx=26,pady=22)
    header=ctk.CTkFrame(body,fg_color='transparent');header.pack(fill='x')
    ctk.CTkLabel(header,text='GPT 划词翻译',font=('Microsoft YaHei UI',25,'bold'),text_color=INK).pack(side='left')
    button(header,'收起',app.hide,width=66).pack(side='right')
    ctk.CTkLabel(body,text='译文直接出现在划词浮框中 · 右键浮框可进入后台',
        font=('Microsoft YaHei UI',12),text_color=MUTED,anchor='w').pack(fill='x',pady=(4,16))
    card=ctk.CTkFrame(body,corner_radius=20,fg_color=CARD,border_width=1,border_color=LINE)
    card.pack(fill='x',pady=(0,14))
    row=ctk.CTkFrame(card,fg_color='transparent');row.pack(fill='x',padx=18,pady=(16,8))
    app.auto=tk.BooleanVar(value=app.settings.get('auto_popup',True))
    ctk.CTkSwitch(row,text='划词翻译',variable=app.auto,command=app.save_settings,
        font=('Microsoft YaHei UI',13),text_color=INK,progress_color=PINK,button_color='white',
        button_hover_color='#FFF8FC',fg_color='#E7DEE4',switch_width=34,switch_height=20).pack(side='left')
    app.model=ModelPicker(row);app.model.pack(side='right');app.model.bind('<<ComboboxSelected>>',app.model_selected)
    row=ctk.CTkFrame(card,fg_color='transparent');row.pack(fill='x',padx=18,pady=(2,16))
    app.auto_model=tk.BooleanVar(value=app.settings.get('auto_model',True))
    ctk.CTkSwitch(row,text='自动跟随模型更新',variable=app.auto_model,command=app.model_mode_changed,
        font=('Microsoft YaHei UI',12),text_color=MUTED,progress_color=PINK,button_color='white',
        fg_color='#E7DEE4',switch_width=34,switch_height=20).pack(side='left')
    button(row,'更新模型',lambda:app.refresh_models(manual=True),width=88).pack(side='right')
    app.status=tk.StringVar(value='正在连接 ChatGPT 套餐…')
    ctk.CTkLabel(body,textvariable=app.status,text_color=MUTED,font=('Microsoft YaHei UI',12),
        anchor='w',wraplength=630,justify='left').pack(fill='x',pady=(0,12))
    ctk.CTkLabel(body,text='原文',text_color=INK,font=('Microsoft YaHei UI',13,'bold'),anchor='w').pack(fill='x')
    app.source=ctk.CTkTextbox(body,height=118,corner_radius=18,border_width=1,border_color=LINE,
        fg_color=CARD,text_color=INK,font=('Microsoft YaHei UI',13),wrap='word',
        border_spacing=12,exportselection=False,undo=True,scrollbar_button_color='#D8C9D3')
    app.source.pack(fill='x',pady=(7,12))
    row=ctk.CTkFrame(body,fg_color='transparent');row.pack(fill='x',pady=(0,16))
    app.translate_button=button(row,'翻译',lambda:app.translate(app.source.get('1.0','end-1c'),floating=False),True,width=92)
    app.translate_button.pack(side='left')
    button(row,'翻译剪贴板',app.translate_clipboard,width=112).pack(side='left',padx=8)
    button(row,'试译示例',lambda:app.translate('Text selection translation is ready.',floating=False),width=88).pack(side='left')
    app.cancel_button=button(row,'取消',app.cancel.set,width=64);app.cancel_button.configure(state='disabled');app.cancel_button.pack(side='right')
    ctk.CTkLabel(body,text='译文',text_color=INK,font=('Microsoft YaHei UI',13,'bold'),anchor='w').pack(fill='x')
    # Pack the footer first so it remains visible when the window is shorter.
    footer=ctk.CTkFrame(body,fg_color='transparent');footer.pack(side='bottom',fill='x',pady=(14,0))
    ctk.CTkLabel(footer,text='Ctrl+Alt+T  划词翻译   ·   不保存翻译历史',text_color=MUTED,
        font=('Microsoft YaHei UI',11)).pack(anchor='w',pady=(10,0),side='bottom')
    button(footer,'复制译文',app.copy_result,width=86).pack(side='left')
    button(footer,'登录 / 重新连接',app.login,width=132).pack(side='left',padx=8)
    button(footer,'退出程序',app.exit,width=86).pack(side='right')
    app.result=ctk.CTkTextbox(body,height=126,corner_radius=18,border_width=1,border_color='#F0E1EB',
        fg_color=SOFT,text_color=INK,font=('Microsoft YaHei UI',13),wrap='word',border_spacing=12,
        state='disabled',exportselection=False,scrollbar_button_color='#D8BDD0')
    app.result.pack(fill='both',expand=True,pady=(7,0))
    return root
