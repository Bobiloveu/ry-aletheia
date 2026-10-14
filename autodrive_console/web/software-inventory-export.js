// A compact, offline report layout. Measure before drawing so identifiers and
// vehicle details remain complete, and allocate only each page's actual size.
const WIDTH = 1200;
const MARGIN = 56;
const CONTENT = WIDTH - MARGIN * 2;
const SANS = 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
const MONO = 'ui-monospace, "SFMono-Regular", Consolas, monospace';
const INK = '#1d1d1f';
const SECONDARY = '#636368';
const SEPARATOR = '#e5e5ea';
const FONT = {
  package: `600 24px ${SANS}`,
  filename: `400 18px ${MONO}`,
  version: `600 24px ${MONO}`,
  architecture: `400 20px ${MONO}`,
  value: `500 24px ${SANS}`,
};

export function wrapInventoryText(context, value, width) {
  const lines = [];
  let line = '';
  for (const character of String(value || '—')) {
    if (character === '\n') {
      lines.push(line);
      line = '';
    } else if (line && context.measureText(line + character).width > width) {
      lines.push(line);
      line = character;
    } else {
      line += character;
    }
  }
  if (line || !lines.length) lines.push(line);
  return lines;
}

function measuredLines(context, value, width, font) {
  context.font = font;
  return wrapInventoryText(context, value, width);
}

function text(context, value, x, y, font, color = INK, align = 'left') {
  context.font = font;
  context.fillStyle = color;
  context.fillText(value, align === 'right' ? x - context.measureText(value).width : x, y);
}

function lines(context, values, x, y, step, font, color = INK) {
  values.forEach((value, index) => text(context, value, x, y + index * step, font, color));
}

function rounded(context, x, y, width, height, radius, color) {
  context.fillStyle = color;
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
  context.fill();
}

function rule(context, y) {
  context.strokeStyle = SEPARATOR;
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(MARGIN, y + .5);
  context.lineTo(WIDTH - MARGIN, y + .5);
  context.stroke();
}

function vehicleLayout(context, vehicle) {
  const groups = [
    [['车号', vehicle.vehicle_number], ['车架号', vehicle.vin], ['车型', vehicle.model]],
    [['项目/客户', vehicle.project], ['部署地点', vehicle.location]],
  ];
  let y = 176;
  const fields = [];
  for (const group of groups) {
    const cellWidth = (CONTENT - 48) / group.length;
    let height = 0;
    group.forEach(([label, value], index) => {
      const wrapped = measuredLines(context, value, cellWidth - 30, FONT.value);
      fields.push({ label, values: wrapped, x: MARGIN + 24 + index * cellWidth, y });
      height = Math.max(height, 31 + wrapped.length * 30);
    });
    y += height + 18;
  }
  return { fields, bottom: y + 6 };
}

function packageLayout(context, item) {
  const name = measuredLines(context, item.package_name, 620, FONT.package);
  const filename = measuredLines(context, item.package_filename, 620, FONT.filename);
  const version = measuredLines(context, item.version, 210, FONT.version);
  const architecture = measuredLines(context, item.architecture, 150, FONT.architecture);
  const height = Math.max(88, name.length * 29 + filename.length * 23 + 30,
    version.length * 29 + 36, architecture.length * 26 + 36);
  return { name, filename, version, architecture, height };
}

function beijingTime(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function* createInventoryExportPages({ document, snapshot, generatedAt = new Date(), maxHeight = 4096 }) {
  const measure = document.createElement('canvas').getContext('2d');
  if (!measure) throw new Error('无法生成版本图片。');
  const vehicle = vehicleLayout(measure, snapshot.vehicle);
  const headingY = vehicle.bottom + 50;
  const tableTop = headingY + 24;
  const rowTop = tableTop + 52;
  const footerHeight = 120;
  const packages = snapshot.packages.map(item => packageLayout(measure, item));
  const pages = [];
  let current = [], bottom = rowTop;
  for (const item of packages) {
    if (bottom + item.height + footerHeight > maxHeight && current.length) {
      pages.push({ rows: current, bottom });
      current = [];
      bottom = rowTop;
    }
    if (bottom + item.height + footerHeight > maxHeight) {
      throw new Error('软件信息过长，无法完整放入版本图片。');
    }
    current.push(item);
    bottom += item.height;
  }
  if (current.length || !pages.length) pages.push({ rows: current, bottom: packages.length ? bottom : rowTop + 100 });

  for (let pageIndex = 0; pageIndex < pages.length; pageIndex++) {
    const page = pages[pageIndex];
    const canvas = document.createElement('canvas');
    canvas.width = WIDTH;
    canvas.height = Math.ceil(page.bottom + footerHeight);
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法生成版本图片。');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);

    text(context, 'RY Aletheia', MARGIN, 58, `600 22px ${SANS}`, SECONDARY);
    text(context, '软件版本清单', MARGIN, 116, `700 44px ${SANS}`);
    text(context, '生成时间 · 北京时间', WIDTH - MARGIN, 56, `400 18px ${SANS}`, SECONDARY, 'right');
    text(context, beijingTime(generatedAt), WIDTH - MARGIN, 88, `500 21px ${MONO}`, INK, 'right');

    rounded(context, MARGIN, 152, CONTENT, vehicle.bottom - 152, 18, '#f5f5f7');
    for (const field of vehicle.fields) {
      text(context, field.label, field.x, field.y + 16, `400 18px ${SANS}`, SECONDARY);
      lines(context, field.values, field.x, field.y + 48, 30, FONT.value);
    }

    text(context, '已安装的软件', MARGIN, headingY, `600 26px ${SANS}`);
    const count = `${packages.length} 项软件${pages.length > 1 ? `  ·  第 ${pageIndex + 1} / ${pages.length} 页` : ''}`;
    text(context, count, WIDTH - MARGIN, headingY, `400 19px ${SANS}`, SECONDARY, 'right');
    rounded(context, MARGIN, tableTop, CONTENT, 50, 10, '#f5f5f7');
    const x = [MARGIN + 18, MARGIN + 664, MARGIN + 904];
    ['软件包 / 标准安装包名', '版本', '架构'].forEach((label, index) => {
      text(context, label, x[index], tableTop + 32, `500 18px ${SANS}`, SECONDARY);
    });

    let y = rowTop;
    for (const row of page.rows) {
      lines(context, row.name, x[0], y + 33, 29, FONT.package);
      lines(context, row.filename, x[0], y + 33 + row.name.length * 29, 23, FONT.filename, SECONDARY);
      lines(context, row.version, x[1], y + 35, 29, FONT.version);
      lines(context, row.architecture, x[2], y + 35, 26, FONT.architecture, SECONDARY);
      y += row.height;
      rule(context, y);
    }
    if (!page.rows.length) text(context, '当前未发现已安装的 ry-* 软件包。', x[0], rowTop + 55, `400 22px ${SANS}`, SECONDARY);
    text(context, '数据来源：本机已安装的 ry-* Debian 软件包', MARGIN, page.bottom + 42, `400 18px ${SANS}`, SECONDARY);
    text(context, '标准安装包名由包名、版本和架构组成，不代表原始下载文件名。', MARGIN, page.bottom + 72, `400 17px ${SANS}`, SECONDARY);
    yield canvas;
  }
}
