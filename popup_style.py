"""Selection action, flowing loading highlight, and streamed inline result."""
from pathlib import Path
import math
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageDraw, ImageFont, ImageTk
import native_windows as native

PINK='#FBE3EC'
INK='#42343E'
LINE='#EFD2E1'


class TranslationPopup(tk.Toplevel):
    def __init__(self,root,translate,open_dashboard,copy_result,cancel):
        super().__init__(root,takefocus=False)
        self.withdraw();self.overrideredirect(True);self.attributes('-topmost',True)
        self.configure(bg=PINK);self.scale=root.winfo_fpixels('1i')/96
        self.font=tkfont.Font(self,family='Microsoft YaHei UI',size=9)
        self.base_width=round(82*self.scale);self.base_height=round(28*self.scale)
        self.width,self.height=self.base_width,self.base_height
        self.anchor_position=None;self.phase='idle';self.value='';self.shimmer_tick=0
        self.dismissed=False
        self.animation=None;self.render_job=None;self.frames=[];self.menu=None
        self.translate_command=translate;self.open_dashboard=open_dashboard
        self.copy_command=copy_result;self.cancel_command=cancel
        self.canvas=tk.Canvas(self,width=self.width,height=self.height,bg=PINK,bd=0,highlightthickness=0,cursor='hand2')
        self.canvas.pack()
        self.mark=ImageTk.PhotoImage(Image.open(Path(__file__).parent/'assets/chatgpt-mark-small.png').convert('RGBA'),master=self)
        self.text=tk.Text(self,wrap='word',font=self.font,bd=0,highlightthickness=0,
            bg=PINK,fg=INK,selectbackground='#ECC6DD',selectforeground=INK,
            padx=0,pady=0,state='disabled',exportselection=False,cursor='xterm',spacing1=1,spacing3=1)
        self.canvas.bind('<ButtonRelease-1>',lambda event:self.translate_command() if self.phase=='idle' else None)
        for widget in (self,self.canvas,self.text):widget.bind('<Button-3>',self.context_menu)
        self.bind('<Map>',self.mapped)
        self.draw_action()

    def contains(self,x,y):
        def within(widget):
            return bool(widget and widget.winfo_exists() and widget.winfo_viewable() and
                widget.winfo_rootx()<=x<widget.winfo_rootx()+widget.winfo_width() and
                widget.winfo_rooty()<=y<widget.winfo_rooty()+widget.winfo_height())
        return within(self) or within(self.menu)

    def mapped(self,event):
        if event.widget is self:self.apply_region()

    def apply_region(self):
        hwnd=native.ancestor(self.winfo_id(),2)
        native.no_activate(hwnd)
        native.round_window(hwnd,self.width,self.height,round(10*self.scale))

    def draw_background(self):
        self.canvas.delete('all')
        w,h=self.width,self.height;r=round(10*self.scale)
        self.canvas.create_polygon(r,0,w-r,0,w,0,w,r,w,h-r,w,h,w-r,h,r,h,0,h,0,h-r,0,r,0,0,
            smooth=True,splinesteps=36,fill=PINK,outline=LINE,width=1)

    def draw_action(self):
        self.draw_background();self.text.place_forget()
        center=self.width/2
        self.canvas.create_image(center-round(17*self.scale),self.height/2,image=self.mark)
        self.canvas.create_text(center+round(10*self.scale),self.height/2,text='翻译',font=self.font,fill=INK)

    def stop_animation(self):
        if self.animation:
            self.after_cancel(self.animation);self.animation=None

    def place_at(self,width,height,position=None):
        if position is not None:self.anchor_position=position
        if self.anchor_position is None:
            x,y=native.point();self.anchor_position=(x+round(14*self.scale),y+round(16*self.scale))
        x,y=self.anchor_position
        left,top,right,bottom=native.work_area(x,y)
        x=max(left+4,min(x,right-width-8));y=max(top+4,min(y,bottom-height-8))
        self.width,self.height=width,height
        self.canvas.configure(width=width,height=height)
        self.geometry(f'{width}x{height}+{x}+{y}')
        self.deiconify();self.apply_region()
        native.show_no_activate(native.ancestor(self.winfo_id(),2),x,y,width,height)

    def idle(self,position):
        self.stop_animation();self.phase='idle';self.value='';self.close_menu();self.dismissed=False
        self.place_at(self.base_width,self.base_height,position);self.draw_action()

    def build_shimmer(self):
        factor=self.scale;size=round(16*factor);gap=round(6*factor)
        font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',round(12*factor))
        bounds=font.getbbox('翻译');tw=bounds[2]-bounds[0];th=bounds[3]-bounds[1]
        w,h=size+gap+tw,max(size,th)+4
        mask=Image.new('L',(w,h),0)
        icon=Image.open(Path(__file__).parent/'assets/chatgpt-mark-small.png').convert('RGBA').resize((size,size),Image.Resampling.LANCZOS)
        mask.paste(icon.getchannel('A'),(0,(h-size)//2))
        ImageDraw.Draw(mask).text((size+gap-bounds[0],(h-th)//2-bounds[1]),'翻译',font=font,fill=255)
        base=(99,73,92);light=(255,245,253)
        for step in range(42):
            center=-w*.35+step/41*w*1.7
            frame=Image.new('RGBA',(w,h));pixels=frame.load()
            for x in range(w):
                for y in range(h):
                    glow=math.exp(-((x-y*.22-center)/(w*.16))**2)
                    pixels[x,y]=tuple(round(a+(b-a)*glow) for a,b in zip(base,light))+(mask.getpixel((x,y)),)
            self.frames.append(ImageTk.PhotoImage(frame,master=self))

    def animate(self):
        if self.phase!='loading':return
        self.draw_background()
        self.canvas.create_image(self.width/2,self.height/2,image=self.frames[self.shimmer_tick%len(self.frames)])
        self.shimmer_tick+=1;self.animation=self.after(38,self.animate)

    def loading(self,position=None):
        self.stop_animation();self.phase='loading';self.value='';self.close_menu();self.text.place_forget();self.dismissed=False
        self.place_at(self.base_width,self.base_height,position)
        if not self.frames:self.build_shimmer()
        self.shimmer_tick=0;self.animate()

    def set_text(self,value,phase='result'):
        self.stop_animation();self.phase=phase;self.value=value
        if not self.dismissed and not self.render_job:self.render_job=self.after_idle(self.render_text)

    def append(self,value):
        if not value:return
        self.set_text(self.value+value)

    def render_text(self):
        self.render_job=None
        if not self.winfo_exists() or self.dismissed or self.phase not in ('result','error'):return
        s=self.scale;padx=round(11*s);pady=round(5*s)
        x,y=self.anchor_position or native.point()
        left,top,right,bottom=native.work_area(x,y)
        max_width=max(self.base_width,min(round(420*s),right-left-round(28*s)))
        longest=max((self.font.measure(line) for line in self.value.split('\n')),default=0)
        width=max(self.base_width,min(max_width,longest+padx*2+4))
        text_width=width-padx*2
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',self.value);self.text.configure(state='disabled')
        self.text.place(x=padx,y=pady,width=text_width,height=self.font.metrics('linespace'))
        self.update_idletasks()
        count=self.text.count('1.0','end-1c','displaylines')
        rows=(count[0] if count else 0)+1
        line_height=self.font.metrics('linespace')+2
        max_height=min(round(320*s),max(self.base_height,bottom-top-round(40*s)))
        height=max(self.base_height,min(max_height,rows*line_height+pady*2))
        self.place_at(width,height);self.draw_background()
        self.text.place(x=padx,y=pady,width=text_width,height=height-pady*2)
        self.text.see('end')

    def error(self,message):self.set_text(message,'error')

    def close_menu(self):
        if self.menu and self.menu.winfo_exists():self.menu.destroy()
        self.menu=None

    def context_menu(self,event):
        self.close_menu()
        entries=[('进入后台',self.open_dashboard)]
        if self.value:entries.append(('复制译文',self.copy_command))
        if self.phase=='loading':entries.append(('取消翻译',self.cancel_command))
        entries.append(('关闭浮框',self.dismiss))
        menu=tk.Toplevel(self,takefocus=False);self.menu=menu
        menu.withdraw();menu.overrideredirect(True);menu.attributes('-topmost',True);menu.configure(bg='#FFFDFE')
        w,h=round(136*self.scale),round(32*self.scale)*len(entries)+round(12*self.scale)
        canvas=tk.Canvas(menu,width=w,height=h,bg='#FFFDFE',bd=0,highlightthickness=0,cursor='hand2');canvas.pack()
        row=round(32*self.scale);margin=round(6*self.scale)
        for i,(label,action) in enumerate(entries):
            canvas.create_text(round(15*self.scale),margin+i*row+row/2,text=label,anchor='w',font=self.font,fill=INK)
        def invoke(click):
            index=(click.y-margin)//row
            if 0<=index<len(entries):
                action=entries[index][1];self.close_menu();action()
        canvas.bind('<ButtonRelease-1>',invoke)
        menu.update_idletasks()
        left,top,right,bottom=native.work_area(event.x_root,event.y_root)
        px=max(left,min(event.x_root,right-w-8));py=max(top,min(event.y_root,bottom-h-8))
        menu.geometry(f'{w}x{h}+{px}+{py}');menu.deiconify()
        menu.update_idletasks()
        hwnd=native.ancestor(menu.winfo_id(),2);native.no_activate(hwnd);native.round_window(hwnd,w,h,round(10*self.scale))
        native.show_no_activate(hwnd,px,py,w,h)
        return 'break'

    def dismiss(self):
        self.dismissed=True;self.stop_animation();self.close_menu();self.withdraw()

    def reveal(self,position=None):
        self.dismissed=False
        if self.phase=='loading':
            self.stop_animation();self.place_at(self.width,self.height,position);self.animate()
        elif self.phase in ('result','error'):
            if position is not None:self.anchor_position=position
            self.render_text()

    def destroy(self):
        self.stop_animation()
        if self.render_job:self.after_cancel(self.render_job)
        self.close_menu();super().destroy()


def create_popup(root,command,open_dashboard=None,copy_result=None,cancel=None):
    return TranslationPopup(root,command,open_dashboard or (lambda:None),copy_result or (lambda:None),cancel or (lambda:None))
