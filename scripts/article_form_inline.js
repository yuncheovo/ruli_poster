
        layui.use(["layCascader"],function () {
            let $ = layui.jquery,
                form = layui.form,
                layCascader = layui.layCascader;

            // 渲染富文本编辑器
            let ue = UE.getEditor('article-editor', {
                initialFrameHeight: 600,
                overflow: 'scroll'
            });

            // 渲染日期组件
            layui.laydate.render({
                elem: '#published_at',
                format: 'yyyy-MM-dd HH:mm:ss'
            });

            // 封面图上传
            app.$upload.image('#image-upload', function (data) {
                app.$message.success('上传成功');
                $('#image-view').removeClass('layui-hide').find('img').attr('src', data.url);
                $('#image').val(data.value);
            });

            // 提交表单
            layui.form.on('submit(article-form-submit)', function (data) {
                data.field.content = $.trim(ue.getContent());
                if (!data.field.content) {
                    app.$message.error('文章内容不能为空');
                    return false;
                }
                app.$message.loading();
                app.$http
                    .post('/article/form', data.field)
                    .then((res) => {
                        app.$message.unloading();
                        if (window.self === window.top) {
                            app.$message.success(res.message);
                        } else {
                            parent.reloadTable();
                            parent.app.$message.success(res.message);
                            parent.layer.close(parent.layer.getFrameIndex(window.name));
                        }
                    })
                    .catch((err) => {
                        app.$message.unloading();
                        app.$message.error(err.message);
                    });
                return false;
            });

            let layCascaderObj = layCascader({
                elem: '#category_id',
                clearable: true,
                filterable: true,
                options: [],
                value: 0,
                props: {value: 'id', label: 'name', checkStrictly: true}
            });

            // 异步获取数据（编辑时）
            app.$http
                .get('/common/article-categorys')
                .then((res) => {
                    layCascaderObj.setOptions(res.data)
                })
                .catch((err) => {
                    app.$message.error(err.message);
                });

        });
    