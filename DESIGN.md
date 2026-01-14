我想要实现类似pytest fixture的使用体验，但是scope要用树状的，而且要支持mixin语义。类似 https://github.com/atry/mixin 和 https://github.com/mxmlnkn/ratarmount/pull/163 的方式来实现mixin。

通过decorator来表示需要把一个callable启用依赖注入。

如果类比联合文件系统，应该把scope视为目录，把resource视为文件。而module、package、callable视为挂载前的文件系统定义。

依赖注入总是基于参数的名称而不是基于类型。参数解析算法类似 https://github.com/atry/mixin ，自动在当前scope及其父scope寻找依赖。如果需要复杂路径，则必须依赖显式的Proxy对象。

```python
@resource
def my_callable(uncle: Proxy) -> float:
  return uncle.path.to.resource
```

以上代码相当于根据uncle的名称搜索 `./uncle/` 、 `../uncle/` 、 `../../uncle/` 等等，然后找到第一个存在的scope，然后在该scope下寻找 `path/to/resource` 资源。
如果一个callable的返回值是另一个Proxy对象，那么该资源被视为类似 https://github.com/mxmlnkn/ratarmount/pull/163 的软链接的处理方式。

```python
@resource
def my_scope(uncle: Proxy) -> Proxy:
  return uncle.path.to.another_scope
```
这大致相当于符号链接 ./uncle/path/to/another_scope、 ../uncle/path/to/another_scope、 或者 ../../uncle/path/to/another_scope 等等，取决于第一个存在的uncle的位置。

有一种特殊情况是当依赖项的名称和callable的名称相同时，表示依赖词法域内的同名资源，而不是依赖scope下的同名子scope。
```python
@resource
def my_callable(my_callable: float) -> float:
  return my_callable + 1.0
```
以上代码表示依赖词法域内的同名资源 `my_callable` ，即从 `../my_callable/` 、 `../../my_callable/` 等等位置寻找 `my_callable` 资源，而不会去寻找 `./my_callable/` 这个当前scope下的`my_callable`。这实现了pytest fixture的同名依赖注入语义。

合并module和package时，使用类似 https://github.com/atry/mixin 和 https://github.com/mxmlnkn/ratarmount/pull/163 的算法。

合并N个同名callable时，必须正好有N-1个callable是`@patch` decorator，而正好有1个callable是`@resource` decorator或者`@aggregate` decorator。否则报错。

在整个框架的入口处，用户可以选择传入多个package、module、或者object作为需要联合挂载到一起的根scope，类似 https://github.com/mxmlnkn/ratarmount/pull/163的做法。


如果一个联合挂载后的scope下的某个resource的全部callable实现都是endo，那么这个resource被视为参数。每一个scope对象同时也是Callable以支持参数注入。

callable除了可以用来定义resource之外，也可以用来定义和转换scope。

我已经实现了核心功能，现在还差一些解析module和package的代码没有写完，即以下代码中的NotImplementedError部分。