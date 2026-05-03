const $ = (id) => document.getElementById(id);

async function loadGenres() {
  try {
    const r = await fetch('/api/genres');
    const list = await r.json();
    const sel = $('genre-select');
    sel.innerHTML = '';
    for (const g of list) {
      const opt = document.createElement('option');
      opt.value = g.key;
      opt.textContent = g.supported ? g.label : `${g.label}（暂未支持）`;
      opt.disabled = !g.supported;
      if (g.supported && !sel.value) opt.selected = true;
      sel.appendChild(opt);
    }
  } catch (e) {
    $('upload-error').textContent = '无法加载书种列表：' + e.message;
  }
}
loadGenres();

$('upload-btn').addEventListener('click', async () => {
  const file = $('file-input').files[0];
  if (!file) {
    $('upload-error').textContent = '请先选择 PDF 文件';
    return;
  }
  $('upload-error').textContent = '';
  $('upload-btn').disabled = true;

  const fd = new FormData();
  fd.append('file', file);
  fd.append('book_type', $('genre-select').value || 'practical');

  let resp;
  try {
    resp = await fetch('/api/jobs', { method: 'POST', body: fd });
  } catch (err) {
    $('upload-error').textContent = '上传失败：' + err.message;
    $('upload-btn').disabled = false;
    return;
  }
  if (!resp.ok) {
    const txt = await resp.text();
    $('upload-error').textContent = '上传失败：' + txt;
    $('upload-btn').disabled = false;
    return;
  }
  const { job_id } = await resp.json();
  resetProgressUI();
  $('progress-section').hidden = false;
  watchProgress(job_id);
});

function resetProgressUI() {
  document.querySelectorAll('#stage-list li').forEach((li) => (li.className = ''));
  $('progress-fill').style.width = '0';
  $('progress-text').textContent = '准备中…';
  $('review-section').hidden = true;
  $('review-content').innerHTML = '';
}

function watchProgress(jobId) {
  const es = new EventSource(`/api/jobs/${jobId}/events`);

  es.addEventListener('progress', (e) => {
    const d = JSON.parse(e.data);
    const li = document.querySelector(`#stage-list li[data-stage="${d.stage}"]`);
    if (li) li.className = d.status;
    $('progress-fill').style.width = d.percent + '%';
    const verb = d.status === 'running' ? '运行中' : '完成';
    const retry = d.attempt ? `（质量门控重试 ${d.attempt}/2）` : '';
    $('progress-text').textContent = `阶段 ${d.stage}/8 · ${d.stage_name} · ${verb}${retry}`;
  });

  es.addEventListener('complete', async (e) => {
    const d = JSON.parse(e.data);
    es.close();
    $('progress-fill').style.width = '100%';
    $('progress-text').textContent = '全部完成';
    await loadReview(jobId, d.review_url);
    $('upload-btn').disabled = false;
  });

  es.addEventListener('error', (e) => {
    if (e.data) {
      try {
        const d = JSON.parse(e.data);
        $('progress-text').textContent = `阶段 ${d.stage} 失败：${d.message}`;
        const li = document.querySelector(`#stage-list li[data-stage="${d.stage}"]`);
        if (li) li.className = 'error';
      } catch {}
    } else {
      $('progress-text').textContent = '连接已断开';
    }
    es.close();
    $('upload-btn').disabled = false;
  });
}

async function loadReview(jobId, url) {
  const r = await fetch(url);
  if (!r.ok) {
    $('progress-text').textContent = '加载书评失败：' + r.status;
    return;
  }
  const md = await r.text();
  $('review-content').innerHTML = marked.parse(md);
  $('download-btn').href = `/api/jobs/${jobId}/review.md`;
  $('review-section').hidden = false;
}
