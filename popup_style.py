"""Compact pink selection action with a ChatGPT mark."""
from pathlib import Path
import tkinter as tk
import native_windows as native

PINK = '#FBE3EC'
HOVER = '#F7D3E2'
INK = '#372C33'
BORDER = '#EFD0DC'


def create_popup(root, command):
    popup = tk.Toplevel(root, takefocus=False)
    popup.withdraw()
    popup.overrideredirect(True)
    popup.attributes('-topmost', True)
    popup.configure(bg=PINK)
    scale = root.winfo_fpixels('1i') / 96
    width, height, radius = round(82*scale), round(28*scale), round(10*scale)
    canvas = tk.Canvas(popup, width=width, height=height, bg=PINK,
                       highlightthickness=0, bd=0, cursor='hand2', takefocus=False)
    canvas.pack()
    r=radius
    shape = canvas.create_polygon(
        r,0,width-r,0,width,0,width,r,width,height-r,width,height,
        width-r,height,r,height,0,height,0,height-r,0,r,0,0,
        smooth=True,splinesteps=36,fill=PINK,outline=BORDER,width=1)
    popup.mark = tk.PhotoImage(file=str(Path(__file__).parent/'assets/chatgpt-mark-small.png'))
    # Keep the same optical spacing as the compact native selection action.
    center=width/2
    canvas.create_image(center-round(17*scale),height/2,image=popup.mark)
    canvas.create_text(center+round(10*scale),height/2,text='翻译',fill=INK,
                       font=('Microsoft YaHei UI',9),anchor='center')
    def hover(color):
        canvas.configure(bg=color)
        canvas.itemconfigure(shape,fill=color)
        popup.configure(bg=color)
    canvas.bind('<Enter>',lambda event:hover(HOVER))
    canvas.bind('<Leave>',lambda event:hover(PINK))
    canvas.bind('<ButtonRelease-1>',lambda event:command())
    def mapped(event):
        if event.widget is popup:
            hwnd=native.ancestor(popup.winfo_id(),2)
            native.no_activate(hwnd)
            native.round_window(hwnd,width,height,radius)
    popup.bind('<Map>',mapped)
    return popup
