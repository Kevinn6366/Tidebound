/** 联网开关只控制服务端能力，不在浏览器查询或拦截模型请求。 */
(function () {
    if (window.__WebSearchModLoaded) return;
    window.__WebSearchModLoaded = true;
    const GWC = window.$GWC;
    if (!GWC) throw new Error('GWC API 未就绪');
    if (window.$GWC.getSettings().enableWebSearch === undefined) window.$GWC.updateSettings({ enableWebSearch: false });

    /**
     * 将开关同步到聊天设置，下一次发送时交由后端固定本轮权限。
     * @param {MouseEvent} event - 快捷按钮的点击事件。
     * @returns {void}
     */
    function toggle(event) {
        event.stopPropagation();
        const enabled = !window.$GWC.getSettings().enableWebSearch;
        window.$GWC.updateSettings({ enableWebSearch: enabled });
        GWC.showToast(`联网已${enabled ? '开启' : '关闭'}，下次发送生效`, enabled ? 'success' : 'info');
        render();
    }

    /**
     * 恢复快捷栏按钮并同步当前设置；不获取外部数据或保存服务凭据。
     * @returns {void}
     */
    function render() {
        const bars = Array.from(document.querySelectorAll('.flex.flex-wrap.justify-end'));
        const bar = bars.find(element => element.textContent.includes('Log') || element.textContent.includes('TTS'));
        if (!bar) return;
        let button = document.getElementById('mod-shortcut-search');
        if (!button) {
            button = document.createElement('button');
            button.id = 'mod-shortcut-search';
            button.type = 'button';
            button.onclick = toggle;
            button.title = '允许本轮使用搜索、网页、天气和兴趣工具；下次发送生效';
            bar.insertBefore(button, bar.lastChild);
        }
        const enabled = window.$GWC.getSettings().enableWebSearch === true;
        const label = enabled ? '联网:开' : '联网:关';
        if (button.textContent !== label) button.textContent = label;
        button.setAttribute('aria-pressed', String(enabled));
        button.style.color = enabled ? '#60a5fa' : 'rgba(255,255,255,0.5)';
    }
    // 仅监听节点变化，属性同步不会触发自身递归。
    new MutationObserver(render).observe(document.body, { childList: true, subtree: true });
    window.setInterval(render, 500);
    render();
})();
