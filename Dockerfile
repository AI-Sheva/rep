FROM anaderi/rep-base:0.6
MAINTAINER Andrey Ustyuzhanin <anaderi@yandex-team.ru>

RUN apt-get install -y libffi-dev wget

ENV TEMP /tmp
ENV SHELL /bin/bash

RUN mkdir $TEMP/build
COPY setup.py README.md AUTHORS requirements.txt $TEMP/build/
COPY rep $TEMP/build/rep
COPY run.sh /root/
COPY howto /REP_howto
RUN cd $TEMP/build && \
  pip install . && \
  rm -rf $TEMP/build

# system setup
#
ENV PORT_IPYTHON=8080

WORKDIR /root/
RUN ipython profile create default &&\
  /bin/echo -e "c.NotebookApp.ip = '*'\nc.NotebookApp.open_browser = False\nc.NotebookApp.port = $PORT_IPYTHON\n" | \
  tee -a /root/.ipython/profile_default/ipython_notebook_config.py

EXPOSE $PORT_IPYTHON
EXPOSE 5000
CMD ["bash", "/root/run.sh"]
