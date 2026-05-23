/* global jQuery */
(() => {
  if (window.__SALES_INIT__) return;
  window.__SALES_INIT__ = true;

  'use strict';
  const qs=(s,el=document)=>el.querySelector(s);
  const qsa=(s,el=document)=>Array.from(el.querySelectorAll(s));
  const on=(el,ev,cb)=>el&&el.addEventListener(ev,cb,{passive:false});
  const toNum=v=>{const n=parseFloat((v??'').toString().replace(/[^\d.-]/g,''));return Number.isFinite(n)?n:0;};
  var stripScripts = window.stripScripts || function(html) { return String(html || '').replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, ''); };
  function loadScriptOnce(src){return new Promise(res=>{if(document.querySelector(`script[src="${src}"]`)) return res();const s=document.createElement('script');s.src=src;s.onload=res;document.head.appendChild(s);});}
  function loadCssOnce(href){if(!document.querySelector(`link[href="${href}"]`)){const l=document.createElement('link');l.rel='stylesheet';l.href=href;document.head.appendChild(l);}}
  function loadJQueryOnce(){return new Promise(res=>{if(window.jQuery) return res();const s=document.createElement('script');s.src='https://cdn.jsdelivr.net/npm/jquery@3.6.4/dist/jquery.min.js';s.onload=()=>res();document.head.appendChild(s);});}
  const debounce=(fn, d=200)=>{let t; return (...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),d);}};
  let salesSearchTimer=null;
  let salesRequestId=0;

  async function fetchProductInfo(pid, wid, targetCurrency){
    if(!(pid && wid)) return {};
    try{
      let url = (window.gmPath || function(p){ return p; })(`/api/products/${pid}/info?warehouse_id=${wid}`);
      if(targetCurrency) url += `&currency=${encodeURIComponent(targetCurrency)}`;
      const res=await fetch(url, {headers:{'Accept':'application/json'}});
      return await res.json();
    }catch(_){ return {}; }
  }

  const initSalesTable=()=>{if(typeof window!=='undefined'&&typeof window.enableTableSorting==='function'){window.enableTableSorting('#salesTable');}};
  // ====== قائمة الفواتير (فلتر) ======
  (function initList(){
    const form = qs('#filterForm');
    if(!form) return;
    const resetBtn = form.querySelector('button[type="reset"]');
    if(resetBtn) on(resetBtn,'click',e=>{
      e.preventDefault();
      const action = form.getAttribute('action') || window.location.pathname;
      window.location = action;
    });
    initSalesTable();
    const salesTableWrapper = qs('#sales-table-wrapper');
    const paginationWrapper = qs('#sales-pagination-wrapper');
    const salesSummaryWrapper = qs('#sales-summary-wrapper');
    const salesSearchInput = qs('#sales-search');
    const salesSearchSummary = qs('#sales-search-summary');
    const sortSelect = qs('#sales-sort');
    const orderSelect = qs('#sales-order');
    const notify = (msg)=>{if(typeof window.showNotification==='function'){window.showNotification(msg,'danger');}else{alert(msg);}};
    const fetchSales = (targetUrl)=>{
      if(!salesTableWrapper) return;
      const urlObj=new URL(targetUrl,window.location.origin);
      urlObj.searchParams.set('ajax','1');
      const requestId=++salesRequestId;
      const previousTable=salesTableWrapper.innerHTML;
      const previousPagination=paginationWrapper?paginationWrapper.innerHTML:'';
      const previousSummary=salesSummaryWrapper?salesSummaryWrapper.innerHTML:'';
      const tbody=salesTableWrapper.querySelector('tbody');
      if(tbody&&typeof window.setLoading==='function'){window.setLoading(tbody,true);}
      return fetch(urlObj.toString(),{headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}}).then(res=>{
        if(!res.ok) throw res;
        return res.json();
      }).then(data=>{
        if(requestId!==salesRequestId) return;
        if(typeof data.table_html==='string'){salesTableWrapper.innerHTML=stripScripts(data.table_html);}
        if(paginationWrapper){paginationWrapper.innerHTML=stripScripts(data.pagination_html||'');}
        if(salesSummaryWrapper){salesSummaryWrapper.innerHTML=stripScripts(data.summary_html||'');}
        if(salesSearchSummary&&typeof data.total_filtered==='number'){salesSearchSummary.textContent=`إجمالي النتائج: ${data.total_filtered}`;}
        initSalesTable();
        urlObj.searchParams.delete('ajax');
        const qstr=urlObj.searchParams.toString();
        const nextUrl=qstr?`${urlObj.pathname}?${qstr}`:urlObj.pathname;
        window.history.replaceState({},'',nextUrl);
      }).catch(()=>{
        if(requestId!==salesRequestId) return;
        salesTableWrapper.innerHTML=previousTable;
        if(paginationWrapper){paginationWrapper.innerHTML=previousPagination;}
        if(salesSummaryWrapper){salesSummaryWrapper.innerHTML=previousSummary;}
        initSalesTable();
        notify('تعذر تحديث القائمة');
      });
    };
    if(paginationWrapper){
      paginationWrapper.addEventListener('click',event=>{
        const link=event.target.closest('a.page-link');
        if(!link) return;
        event.preventDefault();
        fetchSales(link.href);
      });
    }
    if(salesSearchInput){
      const triggerSearch=()=>{
        const currentUrl=new URL(window.location.href);
        const term=salesSearchInput.value.trim();
        if(term){currentUrl.searchParams.set('q',term);}else{currentUrl.searchParams.delete('q');}
        currentUrl.searchParams.delete('page');
        currentUrl.searchParams.set('page','1');
        fetchSales(currentUrl.toString());
      };
      salesSearchInput.addEventListener('input',()=>{
        clearTimeout(salesSearchTimer);
        salesSearchTimer=setTimeout(triggerSearch,350);
      });
    }

    const triggerSort = ()=>{
      const currentUrl=new URL(window.location.href);
      if(sortSelect && sortSelect.value){currentUrl.searchParams.set('sort', sortSelect.value);}
      if(orderSelect && orderSelect.value){currentUrl.searchParams.set('order', orderSelect.value);}
      currentUrl.searchParams.delete('page');
      currentUrl.searchParams.set('page','1');
      fetchSales(currentUrl.toString());
    };
    if(sortSelect) sortSelect.addEventListener('change', triggerSort);
    if(orderSelect) orderSelect.addEventListener('change', triggerSort);
  })();

  // ====== إنشاء/تعديل فاتورة ======
  (function initForm(){
    const form = qs('#saleForm');
    if(!form) return;

    // تاريخ افتراضي
    const saleDateEl = form.querySelector('input[name="sale_date"]');
    if(saleDateEl && !saleDateEl.value){
      const pad=n=>n<10?'0'+n:n; const d=new Date();
      saleDateEl.value = d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes());
    }

    const wantsSelect2 = !!document.querySelector('#saleForm .select2');
    const select2Ready = wantsSelect2
      ? loadJQueryOnce().then(() => {
          // If Select2 is already loaded (from AdminLTE), skip CDN
          if (window.jQuery && window.jQuery.fn && window.jQuery.fn.select2) {
             return Promise.resolve();
          }
          loadCssOnce('https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/css/select2.min.css');
          loadCssOnce('https://cdn.jsdelivr.net/npm/@ttskch/select2-bootstrap4-theme@1.5.2/dist/select2-bootstrap4.min.css');
          return loadScriptOnce('https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js');
      })
      : Promise.resolve();

    // Sortable
    loadScriptOnce('https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js').then(()=>{
      const cont = qs('#saleLines');
      if(cont && window.Sortable){
        new window.Sortable(cont,{handle:'.drag-handle',animation:150,ghostClass:'sortable-ghost'});
      }
    });

    const wrap = qs('#saleLines');
    const addBtn = qs('#addLine');

    function currentMaxIndex(){
      let max=-1;
      qsa('.sale-line',wrap).forEach(row=>{
        if(row.dataset.index && !Number.isNaN(+row.dataset.index)){ max=Math.max(max,+row.dataset.index); return; }
        const any = row.querySelector('input,select,textarea');
        const m = any && (any.name||'').match(/lines-(\d+)-/);
        if(m) max=Math.max(max,+m[1]);
      });
      return Math.max(max,-1);
    }

    function renumberRow(row, i){
      row.dataset.index=i;
      qsa('input,select,textarea',row).forEach(el=>{
        if(el.name) el.name = el.name.replace(/lines-\d+-/,'lines-'+i+'-');
        if(el.id)   el.id   = el.id.replace(/lines-\d+-/,'lines-'+i+'-');
      });
      qsa('label',row).forEach(el=>{
        if(el.htmlFor) el.htmlFor = el.htmlFor.replace(/lines-\d+-/,'lines-'+i+'-');
      });
    }

    function clearRow(row){
      // مسح كل الحقول بشكل صحيح
      qsa('input[type="number"],input[type="text"]',row).forEach(el=>{ 
        el.value=''; 
        el.removeAttribute('value');
      });
      
      // إذا كان Select2 موجود، دمّره أولاً
      if(window.jQuery){
        const $ = window.jQuery;
        $(row).find('select').each(function(){
          const $sel = $(this);
          try {
            // تنظيف s2-initialized لضمان إعادة التهيئة
            $sel.removeData('s2-initialized').removeAttr('data-s2-initialized');
            
            if($sel.data('select2')){
              $sel.select2('destroy');
            }
          } catch(e) {
            // تجاهل الأخطاء
          }
        });
      }
      
      // مسح Select بشكل كامل - حذف كل الـ options ووضع option فارغ
      qsa('select',row).forEach(s=>{
        // حذف كل الخيارات الموجودة
        s.innerHTML = '';
        
        // إضافة option فارغ
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = '';
        s.appendChild(emptyOption);
        
        // إعادة تعيين القيمة
        s.value = '';
        s.selectedIndex = 0;
        
        // إزالة أي classes أو attributes متعلقة بـ Select2
        s.classList.remove('select2-hidden-accessible');
        s.removeAttribute('data-select2-id');
        s.removeAttribute('aria-hidden');
        s.removeAttribute('tabindex');
      });
      
      const badge=row.querySelector('.stock-badge'); 
      if(badge) badge.textContent='';
      row.dataset.priceManual = '';
    }

    function addLine(){
      const rows = qsa('.sale-line',wrap);
      if(!rows.length){ alert('لا يوجد قالب بند لنسخه.'); return; }
      
      // نسخ الصف
      const clone = rows[rows.length-1].cloneNode(true);
      
      // حذف جميع عناصر Select2 المنسوخة (الواجهة المرئية)
      qsa('.select2-container', clone).forEach(el => el.remove());
      
      // مسح جميع البيانات من الصف المنسوخ
      clearRow(clone);
      
      // إزالة أي span متبقي من Select2
      qsa('span[class*="select2"]', clone).forEach(el => el.remove());

      // منع app.js من تهيئة Select2 على العناصر الجديدة
      // لأننا سنقوم بتهيئتها يدوياً في bindRow
      if(window.jQuery){
        const $ = window.jQuery;
        $(clone).find('select').each(function(){
          $(this).data('s2-initialized', 1);
        });
      }
      
      // إعادة ترقيم الصف الجديد
      renumberRow(clone, currentMaxIndex()+1);
      
      // إضافة الصف
      wrap.appendChild(clone);
      
      // ربط الأحداث بعد تأخير قصير للتأكد من إضافة الصف للـ DOM
      setTimeout(() => {
        bindRow(clone);
      }, 100);
      
      // إعادة حساب الإجماليات
      recalc();
    }

    function removeLine(row){
      const rows = qsa('.sale-line',wrap);
      if(rows.length<=1){
        if (typeof toastr !== 'undefined') toastr.warning('يجب ترك بند واحد على الأقل.');
        else alert('يجب ترك بند واحد على الأقل.');
        return;
      }
      row.remove();
      qsa('.sale-line',wrap).forEach((r,i)=>renumberRow(r,i));
      recalc();
    }

    // ----- Select2 helpers -----
    function isSelect2($el){ try{ return !!($el.data('select2') || $el.hasClass('select2-hidden-accessible')); }catch(_){ return false; } }
    function reinitSelect2($el, opts){
      // الاحتفاظ بالقيمة المحددة مسبقاً
      const currentVal = $el.val();
      const selectedOption = currentVal ? $el.find('option:selected').clone() : null;
      
      try{
        if(isSelect2($el)) $el.off().select2('destroy');
      }catch(_){}
      
      // استعادة القيمة المحددة مسبقاً
      if(selectedOption){
        $el.empty().append(selectedOption);
      } else {
        $el.empty();
      }
      
      $el.select2(opts);
      
      // تعيين القيمة مرة أخرى
      if(currentVal){
        $el.val(currentVal).trigger('change.select2');
      }
    }
    function initAjaxSelect($el, {endpoint, placeholder}){
      // الاحتفاظ بالقيمة المحددة مسبقاً
      const currentVal = $el.val();
      const hasSelected = currentVal && $el.find('option:selected').length > 0;
      const selectedOption = hasSelected ? $el.find('option:selected').clone() : null;
      
      const build = () => ({
        theme: 'bootstrap4',
        width: '100%',
        language: 'ar',
        allowClear: !!$el.data('allow-clear'),
        placeholder: placeholder || $el.data('placeholder') || '',
        ajax: {
          delay: 200,
          transport: function (params, success, failure) {
            const url = (typeof endpoint === 'function') ? endpoint() : endpoint;
            params.url = url;
            return jQuery.ajax(params).then(success).catch(failure);
          },
          data: params => ({ q: params.term || '', limit: 50 }),
          // يقبل {results: [...]} أو Array مباشرة
          processResults: data => ({ results: (data && data.results) ? data.results : data })
        }
      });
      
      if(isSelect2($el)){
        try{
          // استخدام destroy فقط دون off() للحفاظ على الأحداث الأخرى
          $el.select2('destroy');
        }catch(_){}
      }
      
      // استعادة القيمة المحددة مسبقاً قبل التهيئة
      if(selectedOption){
        $el.empty().append(selectedOption);
      } else {
        $el.empty();
      }
      
      $el.select2(build());
      $el.data('s2-initialized', 1); // Prevent app.js from re-initializing

      
      // تعيين القيمة مرة أخرى
      if(currentVal){
        $el.val(currentVal).trigger('change.select2');
      }
    }

    function bindRow(row){
      const rm = row.querySelector('.remove-line');
      if(rm) on(rm,'click',()=>removeLine(row));

      const priceInp = row.querySelector('input[name$="-unit_price"]');
      if(priceInp){on(priceInp,'input',()=>{row.dataset.priceManual='1';recalcDebounced();});}

      const nums = qsa('.quantity-input,.price-input,.discount-input,.tax-input',row);
      nums.forEach(el=>{ on(el,'input',recalcDebounced); on(el,'change',recalcDebounced); });

      select2Ready.then(()=>{
        if(!(window.jQuery && window.jQuery.fn && window.jQuery.fn.select2)) return;
        const $ = window.jQuery;
        const $wh = $(row).find('select.warehouse-select');
        const $pd = $(row).find('select.product-select');

        if ($wh.length) {
          initAjaxSelect($wh, {
            endpoint: () => $wh.data('endpoint') || (window.gmPath || function(p){ return p; })('/api/search_warehouses'),
            placeholder: $wh.data('placeholder') || '#'
          });
          
          // عرض رقم المستودع بدلاً من الاسم بعد الاختيار
          // (Removed cosmetic code that caused selection issues)
        }

        const initProducts = () => {
          if (!$pd.length) return;
          const wid = $wh.val();
          const gp = window.gmPath || function(p){ return p; };
          const endpoint = wid ? gp(`/api/warehouses/${wid}/products`) : ($pd.data('endpoint') || gp('/api/products'));
          initAjaxSelect($pd, {
            endpoint: () => endpoint,
            placeholder: $pd.data('placeholder') || 'اختر الصنف'
          });
          $pd.off('select2:select.sales').on('select2:select.sales', async (e) => {
            // عند اختيار صنف جديد، نلغي وضع السعر اليدوي ليتم جلب السعر الجديد
            if(priceInp) row.dataset.priceManual = '';

            const data = e.params?.data || {};
            const pid = +$pd.val(); const widNow = +$wh.val();
            const saleCurrency = qs('select[name="currency"]')?.value || 'ILS';
            if (priceInp) {
              const info=await fetchProductInfo(pid,widNow,saleCurrency);
              if(info && toNum(info.price)>0){
                priceInp.value=toNum(info.price).toFixed(2);
                if(info.original_currency && info.original_currency !== info.target_currency){
                  updateFxRateDisplay(info);
                }
                recalc();
              }
            }
            updateAvailability(pid,widNow,row,saleCurrency);
          });
        };

        initProducts();

        if ($wh.length) {
          // استخدام أحداث Select2 المباشرة بدلاً من change لضمان استجابة أفضل
          $wh.off('select2:select.sales select2:unselect.sales').on('select2:select.sales select2:unselect.sales', () => {
            // استخدام timeout بسيط للسماح للواجهة بالاستقرار (إغلاق القائمة المنسدلة)
            setTimeout(() => {
              if ($pd.length) { 
                $pd.val(null).trigger('change'); 
              }
              initProducts();
              const saleCurrency = qs('select[name="currency"]')?.value || 'ILS';
              updateAvailability(+($pd.val()), +($wh.val()), row, saleCurrency);
            }, 10);
          });
        }
      });
    }

    async function updateAvailability(pid,wid,row,targetCurrency){
      const badge = row.querySelector('.stock-badge');
      if (!badge) return;
      if (!(pid && wid)) { badge.textContent=''; return; }
      const data = await fetchProductInfo(pid,wid,targetCurrency);
      const avail = Number.isFinite(+data.available)? +data.available : null;
      badge.textContent = (avail===null?'':'متاح: '+avail);
    }
    
    const fxRatesUsed = new Map();
    
    function updateFxRateDisplay(info){
      if(!info || !info.original_currency || !info.target_currency) return;
      if(info.original_currency === info.target_currency) return;
      
      const key = `${info.original_currency}/${info.target_currency}`;
      const rate = info.price / info.original_price;
      fxRatesUsed.set(key, rate.toFixed(4));
      
      const fxRow = qs('#fxRateRow');
      const fxInfo = qs('#fxRateInfo');
      if(!fxRow || !fxInfo) return;
      
      const entries = Array.from(fxRatesUsed.entries());
      if(entries.length > 0){
        fxInfo.textContent = '';
        entries.forEach(([pair, rate]) => {
          const badge = document.createElement('span');
          badge.className = 'badge bg-info me-1';
          badge.textContent = `${pair} = ${rate}`;
          fxInfo.appendChild(badge);
          fxInfo.appendChild(document.createTextNode(' '));
        });
        fxRow.style.display = '';
      } else {
        fxRow.style.display = 'none';
      }
    }
    
    function clearFxRateDisplay(){
      fxRatesUsed.clear();
      const fxRow = qs('#fxRateRow');
      if(fxRow) fxRow.style.display = 'none';
    }

    function bindAll(){ qsa('.sale-line',wrap).forEach(bindRow); }

    // حسابات - نفس منطق الباكند
    function recalc(){
      let sub=0, totalDiscount=0;
      qsa('.sale-line',wrap).forEach(row=>{
        const q=toNum(qs('[name$="-quantity"]',row)?.value);
        const p=toNum(qs('[name$="-unit_price"]',row)?.value);
        let d=toNum(qs('[name$="-discount_rate"]',row)?.value); d=Math.max(0,Math.min(100,d));
        const lineTotal = q*p;
        sub += lineTotal*(1-d/100);
        totalDiscount += lineTotal*(d/100);
      });
      let globalTax = toNum(qs('#taxRate')?.value); globalTax=Math.max(0,Math.min(100,globalTax));
      const shipping = toNum(qs('#shippingCost')?.value);
      const globalDiscount = toNum(qs('#discountTotal')?.value);
      // نفس منطق الباكند: base = subtotal - discount
      let baseForTax = sub + shipping - globalDiscount;
      if(baseForTax < 0) baseForTax = 0;
      const taxAmt = baseForTax*(globalTax/100);
      const total = baseForTax + taxAmt;
      const set=(sel,val)=>{
        const el=qs(sel); if(!el) return;
        const curr = (qs('select[name="currency"]')?.value) || '';
        el.textContent = Number(val).toFixed(2) + (curr?` ${curr}`:'');
      };
      set('#subtotal', sub);
      set('#taxAmount', taxAmt);
      set('#shippingCostDisplay', shipping);
      set('#discountTotalDisplay', toNum(qs('#discountTotal')?.value));
      set('#baseForTax', baseForTax);
      set('#totalAmount', total);
      set('#totalDiscount', totalDiscount);
    }
    const recalcDebounced = debounce(recalc,150);

    // تهيئة Select2 للعناصر الرأسية (الزبون والموظف)
    select2Ready.then(()=>{
      if(!(window.jQuery && window.jQuery.fn && window.jQuery.fn.select2)) return;
      const $ = window.jQuery;
      // نستخدم كلاس خاص header-select لمنع التعارض مع app.js
      $('#saleForm select.header-select').each(function(){
        const $el = $(this);
        // تخطي إذا كان العنصر داخل بند فاتورة (احتياط)
        if ($el.closest('.sale-line').length) return;
        
        const endpoint = $el.data('endpoint');
        if(!endpoint) return;
        initAjaxSelect($el, { endpoint, placeholder: $el.data('placeholder') || '' });
      });
    });

    bindAll();
    if (addBtn) on(addBtn,'click',addLine);
    const taxRate = qs('#taxRate'); if (taxRate) on(taxRate,'input',recalcDebounced);
    const shipping= qs('#shippingCost'); if (shipping) on(shipping,'input',recalcDebounced);
    const discountTotal= qs('#discountTotal'); if (discountTotal) on(discountTotal,'input',recalcDebounced);
    const currency= qs('select[name="currency"]');
    if (currency) {
      on(currency,'change', async () => {
        const newCurrency = currency.value || 'ILS';
        clearFxRateDisplay();
        const rows = qsa('.sale-line', wrap);
        for (const row of rows) {
          const $pd = window.jQuery ? window.jQuery(row).find('select.product-select') : null;
          const $wh = window.jQuery ? window.jQuery(row).find('select.warehouse-select') : null;
          const priceInp = row.querySelector('input[name$="-unit_price"]');
          if ($pd && $pd.val() && $wh && $wh.val() && priceInp && row.dataset.priceManual !== '1') {
            const pid = +$pd.val();
            const wid = +$wh.val();
            try {
              const info = await fetchProductInfo(pid, wid, newCurrency);
              if (info && toNum(info.price) > 0) {
                priceInp.value = toNum(info.price).toFixed(2);
                if(info.original_currency && info.original_currency !== info.target_currency){
                  updateFxRateDisplay(info);
                }
              }
            } catch (e) {
            }
          }
        }
        recalcDebounced();
      });
    }
    recalc();
  })();
})();
