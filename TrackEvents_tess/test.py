import tkinter as tk
from idlelib import window
from tkinter import filedialog
import json

import tkinter as tk

# 创建新窗口
result_window = tk.Toplevel(window)

# 创建滚动条
scrollbar = tk.Scrollbar(result_window)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

# 创建文本框
result_text = tk.Text(result_window, yscrollcommand=scrollbar.set)
result_text.pack(side=tk.LEFT, fill=tk.BOTH)

# 将滚动条与文本框关联
scrollbar.config(command=result_text.yview)

# 设置结果文本
result_text.insert(tk.END, "这里是结果内容...\n" * 100)  # 示例：插入100行文本

# 显示结果窗口
result_window.mainloop()

