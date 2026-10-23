# 视频文件实际解码与受控存储

主任务授权接入实际文件技术校验，无真实供应商调用。范围仅video_files.py、video_probe.py、test_video_files.py。PyAV19.0.2由主任务安装。

采用独立Python子进程，固定MP4/WebM demux格式、内存BytesIO输入、禁止外部io_open与网络协议；30秒超时，限制字节、像素、帧数、时长。逐包解码所有视频和音频流；成功仅代表技术文件校验，不代表语义和音画质量。

先写真实libx264 MP4 fixture及错误输入/存储/超时测试，再实现。官方依据：https://pyav.basswood.io/docs/stable/api/_globals.html，已读取av.open(file-like,format,io_open)契约。
