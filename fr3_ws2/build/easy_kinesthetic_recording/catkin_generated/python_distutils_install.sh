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

echo_and_run cd "/home/ravi/fr3_ws2/src/easy_kinesthetic_recording"

# ensure that Python install destination exists
echo_and_run mkdir -p "$DESTDIR/home/ravi/fr3_ws2/install/lib/python3/dist-packages"

# Note that PYTHONPATH is pulled from the environment to support installing
# into one location when some dependencies were installed in another
# location, #123.
echo_and_run /usr/bin/env \
    PYTHONPATH="/home/ravi/fr3_ws2/install/lib/python3/dist-packages:/home/ravi/fr3_ws2/build/lib/python3/dist-packages:$PYTHONPATH" \
    CATKIN_BINARY_DIR="/home/ravi/fr3_ws2/build" \
    "/usr/bin/python3" \
    "/home/ravi/fr3_ws2/src/easy_kinesthetic_recording/setup.py" \
     \
    build --build-base "/home/ravi/fr3_ws2/build/easy_kinesthetic_recording" \
    install \
    --root="${DESTDIR-/}" \
    --install-layout=deb --prefix="/home/ravi/fr3_ws2/install" --install-scripts="/home/ravi/fr3_ws2/install/bin"
