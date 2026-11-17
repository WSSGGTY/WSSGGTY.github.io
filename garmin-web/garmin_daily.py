"""从 Garmin 中国站读取数据，生成可核对的每日快报。"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from garminconnect import Garmin

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / '.garmin-private'
REPORTS = ROOT / '健康快报'
STATUS = ROOT / 'garmin-status.json'
CHINA = timezone(timedelta(hours=8))
logging.disable(logging.CRITICAL)


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def status(message, state='working'):
    save_json(STATUS, {'state': state, 'message': message,
                       'time': datetime.now(CHINA).isoformat()})


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def display(value, unit=''):
    if not number(value):
        return '暂无数据'
    return f'{value:,}{unit}'


def make_report(target, summaries, sleep, warnings):
    """只使用明确存在的数值。日期缺失时不把相邻记录当成前一天。"""
    current = summaries.get(target.isoformat(), {})
    previous = summaries.get((target - timedelta(days=1)).isoformat(), {})
    steps = current.get('totalSteps')
    goal = current.get('dailyStepGoal')
    lines = ['我的每日健康快报', f'报告日期 {target.isoformat()}',
             f'读取时间 {datetime.now(CHINA):%Y-%m-%d %H:%M}（北京时间）',
             '数据来源 Garmin Connect 中国站', '', '步数',
             f'当日步数 {display(steps, " 步")}',
             f'当日目标 {display(goal, " 步")}']
    if number(steps) and number(goal) and goal > 0:
        lines.append(f'目标完成率 {steps / goal:.1%}')
    before = previous.get('totalSteps')
    if number(steps) and number(before):
        difference = steps - before
        if difference == 0:
            lines.append('与前一天步数相同。')
        else:
            direction = '多' if difference > 0 else '少'
            lines.append(f'比前一天{direction}走 {abs(difference):,} 步。')
    else:
        lines.append('当日或前一天步数缺失，暂不能比较。')
    week = []
    for offset in range(6, -1, -1):
        day = (target - timedelta(days=offset)).isoformat()
        week.append((day, summaries.get(day, {}).get('totalSteps')))
    values = [value for _, value in week if number(value)]
    if values:
        lines.append(f'近七天有步数记录 {len(values)} 天，日均 {sum(values) / len(values):,.1f} 步。')
    dto = sleep.get('dailySleepDTO') or {}
    seconds = dto.get('sleepTimeSeconds')
    duration = '暂无数据'
    if number(seconds):
        minutes = round(seconds / 60)
        duration = f'{minutes // 60} 小时 {minutes % 60} 分钟'
    lines.extend(['', '日常指标', f'睡眠时长 {duration}',
                  f'静息心率 {display(current.get("restingHeartRate"), " 次/分钟")}',
                  f'平均压力 {display(current.get("averageStressLevel"))}',
                  '', '近七天步数'])
    lines.extend(f'{day}  {display(value, " 步")}' for day, value in week)
    if warnings:
        lines.extend(['', '读取情况', *warnings])
    lines.extend(['', '缺失数据保留为“暂无数据”。睡眠归属沿用 Garmin 返回的日期。',
                  '数据完整性取决于手表佩戴和同步情况。'])
    return '\n'.join(lines)


def error_message(error):
    name = type(error).__name__
    descriptions = {
        'GarminConnectAuthenticationError': '登录验证失败，请确认中国站账号信息，或重新输入账号和密码。',
        'GarminConnectTooManyRequestsError': 'Garmin 限制了请求频率，请稍后再试。',
        'GarminConnectConnectionError': '连接 Garmin 失败，请检查网络或稍后重试。',
        'GarminConnectNotFoundError': 'Garmin 没有提供所请求的数据。',
        'PermissionError': '文件保存失败，请检查文件夹权限。',
        'TimeoutError': '等待验证码超时，请重新连接。',
    }
    return descriptions.get(name, '操作未完成，请把下面的错误类型告诉我。') + f'（{name}）'


def fetch_report(target, email='', password='', mfa=None, progress=status):
    progress('正在连接 Garmin 中国站…')
    api = Garmin(email=email or None, password=password or None, is_cn=True,
                 prompt_mfa=mfa, retry_attempts=1)
    PRIVATE.mkdir(exist_ok=True)
    if email and password:
        api.login()
        api.client.dump(str(PRIVATE))
    else:
        api.login(str(PRIVATE))
    password = ''
    summaries = {}
    warnings = []
    for offset in range(6, -1, -1):
        day = (target - timedelta(days=offset)).isoformat()
        progress(f'已连接，正在读取 {day} 的每日数据…')
        # 日常汇总失败时停止本次生成，防止把连接失败显示为健康数据缺失。
        data = api.get_stats(day)
        if not isinstance(data, dict):
            raise ValueError('Unexpected daily summary')
        returned_date = data.get('calendarDate')
        if returned_date and returned_date != day:
            raise ValueError('Returned date mismatch')
        summaries[day] = data
    progress('正在读取睡眠记录…')
    sleep = {}
    try:
        sleep = api.get_sleep_data(target.isoformat()) or {}
    except Exception as error:
        warnings.append('睡眠读取未完成，' + error_message(error))
    report = make_report(target, summaries, sleep, warnings)
    REPORTS.mkdir(exist_ok=True)
    output = REPORTS / f'{target.isoformat()}.txt'
    temporary = output.with_suffix('.tmp')
    temporary.write_text(report, encoding='utf-8-sig')
    temporary.replace(output)
    save_json(REPORTS / f'{target.isoformat()}.json',
              {'source': 'Garmin China', 'summaries': summaries, 'sleep': sleep})
    status('快报生成成功', 'done')
    return report, output

