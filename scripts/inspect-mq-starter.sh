#!/usr/bin/env bash

set -euo pipefail

image='maven:3.9.11-eclipse-temurin-17'
cache_volume='asterrag-tutorial-m2'
artifact='/root/.m2/repository/org/apache/rocketmq/rocketmq-spring-boot/2.3.6/rocketmq-spring-boot-2.3.6.jar'

docker run --rm \
  -v "${cache_volume}:/root/.m2" \
  "${image}" \
  sh -lc "
    set -eu
    sha256sum '${artifact}'
    javap -classpath '${artifact}' -p -c -v org.apache.rocketmq.spring.autoconfigure.RocketMQAutoConfiguration \
      | grep -E -A8 -B3 'ConditionalOnProperty|rocketMQTemplate|RuntimeVisibleAnnotations'
    javap -classpath '${artifact}' -p -c org.apache.rocketmq.spring.core.RocketMQTemplate \
      | grep -A28 -B3 'afterPropertiesSet'
    javap -classpath '${artifact}' -p -c org.apache.rocketmq.spring.support.DefaultRocketMQListenerContainer \
      | sed -n '510,585p'
  "
