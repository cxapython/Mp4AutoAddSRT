import argparse
import sys
from gen_subtitle import *


def main():
    """
    默认走谷歌api，如果访问不通走百度的。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('source_path', help="Path to the video or audio file to subtitle",
                        nargs='?')
    parser.add_argument('-C', '--concurrency', help="Number of concurrent API requests to make",
                        type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument('-o', '--output',
                        help="Output path for subtitles (by default, subtitles are saved in \
                        the same directory and name as the source path)")
    parser.add_argument('-F', '--format', help="Destination subtitle format",
                        default=DEFAULT_SUBTITLE_FORMAT)
    parser.add_argument('-L', '--lang', help="Language spoken in source file, default 1537",
                        default=DEFAULT_LANGUAGE)
    parser.add_argument('-K', '--api-key',
                        help="The Baidu Cloud API key to be used.")
    parser.add_argument('-S', '--secret-key',
                        help="The Baidu Cloud Secret Key to be used.")
    parser.add_argument('-A', '--app-id',
                        help="The Baidu Cloud AppID to be used.")
    parser.add_argument('--list-formats', help="List all available subtitle formats",
                        action='store_true')
    parser.add_argument('--list-languages', help="List all available source/destination languages",
                        action='store_true')
    parser.add_argument('-st', '--step', type=int, help="执行第几阶段", default=0)
    parser.add_argument('-i', '--ignore_error', type=bool, help="直接用生成的字幕", default=False)

    args = parser.parse_args()

    if args.list_formats:
        print("List of formats:")
        for subtitle_format in FORMATTERS:
            print("{format}".format(format=subtitle_format))
        return 0

    if args.list_languages:
        print("List of all languages:")
        for code, language in sorted(LANGUAGE_CODES.items()):
            print("{code}\t{language}".format(code=code, language=language))
        return 0

    if not validate(args):
        return 1

    try:
        source_path = args.source_path
        step = args.step
        if source_path is not None:
            file_type = os.path.splitext(source_path)[-1]
            wav_file_path = f"{source_path}".replace(file_type, ".wav")
            srt_file_path = f"{source_path}".replace(file_type, ".srt")

        if step == 0:
            # 三个阶段都执行
            step1(source_path)  # 视频文件转换为音频文件【优先wav】
            step2(args.app_id, args.api_key, args.secret_key, wav_file_path, concurrency=1)  # 生成的srt文件路径
            # 手动校对字幕
            if args.ignore_error:
                step3(srt_file_path, source_path)
        elif step == 1:
            step1(source_path)  # 视频文件转换为音频文件【优先wav】
        elif step == 3:
            # 单独执行第三步
            step3(srt_file_path, source_path)

    except KeyboardInterrupt:
        return 1

    return 0


def step1(srouce_path):
    # 视频转为mp3，加快翻译速度
    if srouce_path is not None:
        file_type = os.path.splitext(srouce_path)[-1]
        output = f"{srouce_path}".replace(file_type, ".wav")
    if os.path.exists(output):
        os.remove(output)
    command = ["ffmpeg", "-i", srouce_path, "-f", "wav",
               "-ac", "1", "-ar", "16000",
               "-loglevel", "error", output]
    use_shell = True if os.name == "nt" else False
    subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)


def step2(app_id, api_key, secret_key, source_path, concurrency=1, output=None):
    # 前面生成的wav生成生成srt文件
    try:
        if output is None:
            file_type = os.path.splitext(source_path)[-1]
            output = f"{source_path}".replace(file_type, ".srt")
        subtitle_file_path = create_subtitles(
            source_path=source_path,
            concurrency=concurrency,  # 免费版的并发数也就是1了
            output=output,
            api_key=api_key,
            app_id=app_id,
            secret_key=secret_key,
            # subtitle_file_format="srt" # 指定字幕格式默认是srt的。
        )
        print("Subtitles file created at {}".format(subtitle_file_path))
    except KeyboardInterrupt:
        return 1
    return output


def step3(srt_file_path, video_file_path):
    # srt文件+视频生成字幕
    """
    :param srt_file_path:
    :param video_file_path:
    :return:
    """
    if srt_file_path and video_file_path:
        file_type = os.path.splitext(video_file_path)[-1]
        output = f"{video_file_path}".replace(file_type, f"_result{file_type}")
    if os.path.exists(output):
        os.remove(output)
    # 推荐下载思源字体，或者其他免费的非商业字体，通过Fontname可以修改
    command = ["ffmpeg", "-i", video_file_path, "-lavfi",
               f"subtitles={srt_file_path}:force_style='Alignment=2,Fontsize=18,Fontname=SourceHanSansCN-Medium,MarginV=20'",
               "-crf", "1", "-c:a", "copy", output]
    use_shell = True if os.name == "nt" else False
    subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
    return output


if __name__ == '__main__':
    #     # https://console.bce.baidu.com/ai/#/ai/speech/overview/index
    #     # 免费领用
    #     file_name = "./test.wav"
    # sys.exit(main())
    # file_name = "./test.mov"
    # step1(file_name)
    sys.exit(main())
