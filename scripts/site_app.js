/**
 * 前端常用方法封装
 * @author qiyo
 */
window.app = {
  // 消息
  $message: {
    toast: function (style, message, callback, options) {
      options.timeout = options.timeout === undefined ? 3000 : options.timeout;
      let handler = function () {
        layui.toast[style](Object.assign({
          message: message,
          timeout: 3000,
          onClosed: callback
        }, options));
      }
      if (layui.toast) {
        handler();
      } else {
        layui.use(['toast'], handler);
      }
    },
    info: function (message, callback, timeout) {
      app.$message.toast('info', message, callback, {timeout: timeout});
    },
    success: function (message, callback, timeout) {
      app.$message.toast('success', message, callback, {timeout: timeout});
    },
    warning: function (message, callback, timeout) {
      app.$message.toast('warning', message, callback, {timeout: timeout});
    },
    error: function (message, callback, timeout) {
      app.$message.toast('error', message, callback, {timeout: timeout});
    },
    // 加载层
    loadingIndex: null,
    loading(message) {
      if (message) {
        app.$message.loadingIndex = layer.msg(message, {icon: 16, shade: 0.2, time: 0});
      } else {
        app.$message.loadingIndex = layer.load(0, {shade: 0.2});
      }
      return app.$message.loadingIndex;
    },
    unloading(loadingIndex) {
      if (loadingIndex) {
        layer.close(loadingIndex);
      } else if (app.$message.loadingIndex) {
        layer.close(app.$message.loadingIndex);
        app.$message.loadingIndex = null;
      }
    },
  },
  // 提示框
  $alert: {
    alert(message, callback, options) {
      options.title = options.title || '系统提示：';
      options.shadeClose = options.shadeClose === undefined ? false : options.shadeClose;
      if (options.icon === null || options.icon === undefined) {
        delete options.icon;
      }
      if (callback) {
        let confirm = callback;
        callback = function (index) {
          let res = confirm(index);
          if (res !== false) {
            layer.close(index);
          }
        };
      }
      layer.alert(message, options, callback);
    },
    info(message, callback, options) {
      app.$alert.alert(message, callback, Object.assign({icon: null}, options));
    },
    success(message, callback, options) {
      app.$alert.alert(message, callback, Object.assign({icon: 1}, options));
    },
    warning(message, callback, options) {
      app.$alert.alert(message, callback, Object.assign({icon: 0}, options));
    },
    error(message, callback, options) {
      app.$alert.alert(message, callback, Object.assign({icon: 2}, options));
    },
  },
  // 对话框
  $confirm: {
    confirm(message, confirm, cancel, options) {
      options.title = options.title || '系统提示：';
      if (confirm) {
        let callback = confirm;
        confirm = function (index) {
          let res = callback(index);
          if (res !== false) {
            layer.close(index);
          }
        };
      }
      layer.confirm(message, options, confirm, cancel);
    },
    info(message, confirm, cancel, options) {
      app.$confirm.confirm(message, confirm, cancel, Object.assign({icon: null}, options));
    },
    success(message, confirm, cancel, options) {
      app.$confirm.confirm(message, confirm, cancel, Object.assign({icon: 1}, options));
    },
    warning(message, confirm, cancel, options) {
      app.$confirm.confirm(message, confirm, cancel, Object.assign({icon: 0}, options));
    },
    error(message, confirm, cancel, options) {
      app.$confirm.confirm(message, confirm, cancel, Object.assign({icon: 2}, options));
    },
  },
  // 上传组件
  $upload: {
    // 上传文件
    handler(elem, callback, save_attachment = false, options = {}) {
      // 处理器
      options.data.save_attachment = save_attachment ? 'true' : 'false';
      let handler = function () {
        return layui.upload.render(Object.assign({
          elem: elem,
          multiple: false,
          url: '/site/upload',
          field: 'file',
          error: function () {
            app.$message.error('上传失败！');
          },
          done: function (res) {
            if (res.code === 0) {
              if (callback) {
                callback(res.data);
              }
            } else {
              app.$message.error(res.message);
            }
          }
        }, options || {}));
      };

      // 初始化
      if (layui.upload) {
        return handler();
      } else {
        return layui.use(['upload'], handler);
      }
    },
    // 上传图片
    image(elem, callback, save_attachment = false, options = {}) {
      return app.$upload.handler(elem, callback, save_attachment, Object.assign({
        data: {type: 'image'},
        accept: 'images',
        acceptMime: 'image/*',
        exts: 'jpg|png|gif|webp|svg|ico',
        size: 500, // 单位: KB
      }, options));
    },
    // 上传多张图片
    images(elem, callback, save_attachment = false, options = {}) {
      return app.$upload.image(elem, callback, save_attachment, Object.assign({multiple: true}, options));
    },
    // 上传视频
    video(elem, callback, save_attachment = false, options = {}) {
      return app.$upload.handler(elem, callback, save_attachment, Object.assign({
        data: {type: 'video'},
        accept: 'video',
        acceptMime: 'video/*',
        exts: 'mp4',
        size: 200 * 1024, // 单位: KB
      }, options));
    },
    // 上传音频
    audio(elem, callback, save_attachment = false, options = {}) {
      return app.$upload.handler(elem, callback, save_attachment, Object.assign({
        data: {type: 'audio'},
        accept: 'audio',
        acceptMime: 'audio/*',
        exts: 'mp3',
        size: 100 * 1024, // 单位: KB
      }, options));
    },
    // 上传文档
    document(elem, callback, save_attachment = false, options = {}) {
      return app.$upload.handler(elem, callback, save_attachment, Object.assign({
        data: {type: 'document'},
        accept: 'file',
        acceptMime: 'application/*',
        exts: 'pdf|docx|doc|xlsx|xls|txt|json|csv',
        size: 100 * 1024, // 单位: KB
      }, options));
    },
    // 上传压缩包
    archive(elem, callback, save_attachment = false, options = {}) {
      return app.$upload.handler(elem, callback, save_attachment, Object.assign({
        data: {type: 'archive'},
        accept: 'file',
        acceptMime: 'application/*',
        exts: 'zip|rar|7z|xz|gz|bz2|xlsx|xls',
        size: 200 * 1024, // 单位: KB
      }, options));
    },
  },
  // HTTP请求
  $http: {
    request(config) {
      return new Promise((resolve, reject) => {
        axios(config).then(response => {
          if (response.data.code === 0) {
            resolve(response.data);
          } else if (response.data.code === 401) {
              app.$alert.warning('登录状态已过期，请重新登录！', function () {
              location.href = '/login';
            });
            reject(new Error(response.data.message));
          } else {
            let error = new Error(response.data.message);
            error.response = response;
            reject(error);
          }
        }).catch(error => {
          app.$message.error(error.message);
          reject(error);
        });
      });
    },
    get(url, params) {
      return app.$http.request({method: 'get', url: url, params: params});
    },
    post(url, data) {
      return app.$http.request({method: 'post', url: url, data: data});
    },
    upload(type, file, data) {
      let formData = new FormData();
      formData.append('type', type);
      for (let key in data) {
        formData.append(key, data[key]);
      }
      formData.append('file', file, file.name);
      return app.$http.request({
        method: 'post',
        url: '/site/upload',
        data: formData,
        headers: {
          'Content-Type': 'multipart/form-data',
        }
      });
    },
    uploadImage(file, data) {
      return app.$http.upload('image', file, data);
    },
    uploadVideo(file, data) {
      return app.$http.upload('video', file, data);
    },
    uploadAudio(file, data) {
      return app.$http.upload('audio', file, data);
    },
    uploadDocument(file, data) {
      return app.$http.upload('document', file, data);
    },
    uploadArchive(file, data) {
      return app.$http.upload('archive', file, data);
    },
    download(url, options, fileName) {
      // 防缓存
      let t = (url.indexOf('?') > -1 ? '&' : '?') + '_t=' + Date.now();
      url = url + t;
      return request
        .request(
          Object.assign(
            {
              method: 'get',
              url: url,
              responseType: 'blob'
            },
            options
          )
        )
        .then((res) => {
          if (!fileName) {
            fileName =
              res.headers['content-disposition'].match(/filename=(.*)/)[1];
            if (!fileName) {
              fileName = 'download';
            }
            fileName = decodeURIComponent(fileName);
          }
          let url = window.URL.createObjectURL(new Blob([res.data]));
          let link = document.createElement('a');
          link.style.display = 'none';
          link.href = url;
          // 去掉首尾引号
          fileName = fileName.replace(/(^['"]|['"]$)/g, '');
          link.setAttribute('download', fileName);
          document.body.appendChild(link);
          link.click();
          link.remove();
        })
        .catch((err) => {
          app.$message.error(err.message);
        });
    }
  },
  // 表格
  $table: {
    // 渲染
    render: function (options) {
      // 处理器
      let handler = function () {
        // 设置表格过滤器
        let table_elem = options.elem;
        let filter_name = layui.jquery(table_elem).attr('lay-filter');
        if (!filter_name) {
          filter_name = table_elem.substring(1);
          layui.jquery(table_elem).attr('lay-filter', filter_name);
        }

        // 表格渲染
        return layui.table.render(Object.assign({
          defaultToolbar: ['filter', 'print', {
            title: '刷新表格数据',
            layEvent: 'LAYTABLE_RELOAD',
            icon: 'layui-icon-refresh'
          }],
          page: true,
          limit: 20,
          limits: [10, 20, 30, 40, 50, 100, 200, 500, 1000],
          whereFormatter: function (data) {
            return data;
          },
          before: function (options) {
            options.where.where = {};
            options.where.where = JSON.stringify(Object.assign(options.where.where, this.whereFormatter(layui.form.val(layui.jquery(table_elem).data('page-id') + '-search-form'))));
          },
          // 自定义方法：可用于格式化数据
          dataFormatter: function (data) {
            return data;
          },
          parseData: function (res) {
            return {
              code: res.code,
              msg: res.message,
              count: res.data ? res.data.total : 0,
              data: res.data ? this.dataFormatter(res.data.items) : [],
              _data: res.data
            };
          }
        }, options));
      };

      if (layui.table) {
        return handler();
      } else {
        return layui.use(['table'], handler);
      }
    },
    // 重载
    reload: function (id, options) {
      let config;
      if (id instanceof Object) {
        config = {
          where: id.config.where || {},
          page: id.config.page || {curr: 1},
          limit: id.config.limit || 20
        };
        id = id.config.id;
      } else {
        config = {where: {}};
      }
      if (options) {
        config = Object.assign(config, options);
      }
      layui.table.reload(id, config, false);
    },
    // 重载数据
    reloadData: function (id, options) {
      let config;
      if (id instanceof Object) {
        config = {
          where: id.config.where || {},
          page: id.config.page || {curr: 1},
          limit: id.config.limit || 20
        };
        id = id.config.id;
      } else {
        config = {where: {}};
      }
      if (options) {
        config = Object.assign(config, options);
      }
      layui.table.reloadData(id, config, false);
    },
    // 重载数据
    reloadTreeData: function (id, options) {
      let config;
      if (id instanceof Object) {
        config = {
          where: id.config.where || {},
          page: id.config.page || {curr: 1},
          limit: id.config.limit || 20
        };
        id = id.config.id;
      } else {
        config = {where: {}};
      }
      if (options) {
        config = Object.assign(config, options);
      }
      layui.treeTable.reloadData(id, config, false);
    },
    // 获取选中行
    getSelectedRows: function (id) {
      if (id instanceof Object) {
        id = id.config.id;
      }
      return layui.table.checkStatus(id).data;
    }
  },
  // 弹层
  $layer: {
    iframe: function (title, url, options) {
      let handler = function () {
        return layui.layer.open(Object.assign({
          type: 2,
          title: title,
          content: url,
          shadeClose: false,
          maxmin: true,
          area: ['80%', '95%']
        }, options || {}));
      }
      if (layui.layer) {
        return handler();
      } else {
        return layui.use(['layer'], handler);
      }
    }
  },
  // 工具
  $util: {
    deepCopy(data) {
      return JSON.parse(JSON.stringify(data));
    },
    // 随机颜色
    randomColor() {
      let colors = ['info', 'primary', 'success', 'warning', 'danger'];
      return colors[Math.floor(Math.random() * colors.length)];
    },
    getMoney(value) {
      if (value) {
        value = value.replace(/[^\d.]/g, '');
        value = value.replace(/^\./g, '');
        value = value.replace(/\.{2,}/g, '.');
        value = value
          .replace('.', '$#$')
          .replace(/\./g, '')
          .replace('$#$', '.');
        value = value.replace(/^(-)*(\d+)\.(\d\d).*$/, '$1$2.$3');
        value = value.replace(/^0(\d+.*)/g, '$1');
      }
      value = parseFloat(value);
      return isNaN(value) ? 0 : value;
    },
    getInt(value, min = 0) {
      if (value) {
        value = value + '';
        value = value.replace(/\D/g, '');
        value = value.replace(/0(\d+.*)/g, '$1');
      }
      value = parseInt(value);
      return isNaN(value) ? min : Math.max(min, value);
    }
  },
}
