#!/bin/sh

if [ -n "$DESTDIR" ] ; then
    case $DESTDIR in
        /*) # ok
            ;;
        *)
            /bin/echo "DESTDIR argument must be absolute... "
            /bin/echo "otherwise python's distutils will bork things."
            exit 1
    esac
fi

echo_and_run() { echo "+ $@" ; "$@" ; }

echo_and_run cd "/home/ravi/pragma_ws/src/pragmabot-repro/pragmabot"

# ensure that Python install destination exists
echo_and_run mkdir -p "$DESTDIR/home/ravi/pragma_ws/install/lib/python3/dist-packages"

# Note that PYTHONPATH is pulled from the environment to support installing
# into one location when some dependencies were installed in another
# location, #123.
echo_and_run /usr/bin/env \
    PYTHONPATH="/home/ravi/pragma_ws/install/lib/python3/dist-packages:/home/ravi/pragma_ws/build/pragmabot/lib/python3/dist-packages:$PYTHONPATH" \
    CATKIN_BINARY_DIR="/home/ravi/pragma_ws/build/pragmabot" \
    "/usr/bin/python3" \
    "/home/ravi/pragma_ws/src/pragmabot-repro/pragmabot/setup.py" \
     \
    build --build-base "/home/ravi/pragma_ws/build/pragmabot" \
    install \
    --root="${DESTDIR-/}" \
    --install-layout=deb --prefix="/home/ravi/pragma_ws/install" --install-scripts="/home/ravi/pragma_ws/install/bin"
